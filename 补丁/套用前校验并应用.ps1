# ============================================================================
# 套用前校验并应用.ps1 —— review/ 评分量具修正 交付包
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\套用前校验并应用.ps1 -Target <目标仓根>
#
# 做什么：
#   ① 读同目录《改动清单.txt》的「前像 sha256」节；
#   ② 对每个**非新增**文件算目标树里的 sha256，逐条比对；
#   ③ 任一不符 ⇒ 立即停止，绝不套补丁；列漂移文件 + 退出码 2；
#   ④ 全对才 `git apply --check`；失败 ⇒ 打印 git 原文 + 退出码 1（不套用）；
#   ⑤ `git apply` 成功 ⇒ 打印「套用完成」+ 接着要跑的 11 条命令；
#   ⑥ 参数缺失／补丁不存在 ⇒ 清晰报错 + 退出码 2。
#
# **前置条件**：-Target 必须是一个**已初始化的 git 工作树**（没有 .git 就先 `git -C <目标仓根> init -q`）。
#   原因：`git apply` 在非 git 目录里会把每个 hunk 标成 Skipped **却仍然退出 0**（本机 git 2.56.0.windows.2 实测），
#   即静默什么都不做。本脚本因此显式拒绝非 git 目标，并在套用后**独立复核**（逐文件比对套用前后 sha256）。
#
# 退出码：0 = 校验通过且套用完成 ／ 1 = 前像全对但 git apply --check/apply 失败或 apply 是空动作
#         2 = 前像漂移、参数缺失、清单或补丁缺失、清单格式不可解析、目标不是 git 工作树
#
# 机房：git 用固定绝对路径（不依赖 PATH）；所有文本按 UTF-8 读；git 一律带 core.autocrlf=false。
# ============================================================================

param(
  [string]$Target
)

$ErrorActionPreference = 'Continue'
$script:ExitCode = 0

# 跑一条 git：返回 @{ rc; lines }。**不要把 stderr 当异常**——
# PowerShell 的 $ErrorActionPreference='Stop' 会把原生命令写到 stderr 的普通错误信息
# 变成终止性错误，于是 `git apply --check` 的失败会**绕过**退出码分支。
# 这里把 stderr 也按行收进 lines，由调用方按 rc 显式判定。
function GRun([string[]]$GitArgs) {
  $old = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try   { $o = & $Git @GitArgs 2>&1 }
  finally { $ErrorActionPreference = $old }
  return @{ rc = $LASTEXITCODE; lines = @($o) }
}

try {
  # ---- 固定外部路径 ------------------------------------------------------
  $Git = 'F:\GIT\cmd\git.exe'
  $Py  = 'C:\Users\LENOVO\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
  $PatchName = '量具修正.patch'
  $ManifestName = '改动清单.txt'
  $NewMark = '（新增，无前像）'

  $here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
  $patch = Join-Path $here $PatchName
  $man   = Join-Path $here $ManifestName

  # ---- 参数与文件存在性（退出码 2）--------------------------------------
  if ([string]::IsNullOrWhiteSpace($Target)) {
    Write-Host '【参数缺失】必须给出目标仓根：'
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Target <目标仓根>"
    Write-Host '不套用任何文件。'
    $script:ExitCode = 2
    return
  }
  if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
    Write-Host ("【目标仓根不存在】-Target 指向的目录不存在：{0}" -f $Target)
    Write-Host '不套用任何文件。'
    $script:ExitCode = 2
    return
  }
  $root = (Resolve-Path -LiteralPath $Target).Path
  if (-not (Test-Path -LiteralPath $patch -PathType Leaf)) {
    Write-Host ("【补丁文件不存在】{0}" -f $patch)
    Write-Host ("（本脚本与《{0}》《{1}》必须放在同一目录）" -f $ManifestName, $PatchName)
    $script:ExitCode = 2
    return
  }
  if (-not (Test-Path -LiteralPath $man -PathType Leaf)) {
    Write-Host ("【改动清单不存在】{0}" -f $man)
    $script:ExitCode = 2
    return
  }

  Write-Host '================================================================'
  Write-Host '套用前校验 · review/ 评分量具修正'
  Write-Host '================================================================'
  Write-Host ("目标仓根 : {0}" -f $root)
  Write-Host ("补丁     : {0}（{1} 字节）" -f $patch, (Get-Item -LiteralPath $patch).Length)
  Write-Host ("清单     : {0}" -f $man)
  Write-Host ''

  # ---- ① 读清单「前像 sha256」节 ----------------------------------------
  $lines = [System.IO.File]::ReadAllLines($man, [System.Text.Encoding]::UTF8)
  $inPre = $false
  $pre = New-Object System.Collections.ArrayList   # @{ Path=...; Expected=$null 表新增 }
  $unparsed = New-Object System.Collections.ArrayList
  $reEntry = '^([0-9a-fA-F]{64})  (.+)$'

  foreach ($raw in $lines) {
    $l = $raw
    if ($null -eq $l) { continue }
    $l = $l.Trim()
    if ($l.Length -eq 0) { continue }
    if ($l.StartsWith('== 前像')) { $inPre = $true;  continue }
    if ($l.StartsWith('== 改后')) { $inPre = $false; continue }
    if (-not $inPre) { continue }

    if ($l.StartsWith($NewMark)) {
      $p = $l.Substring($NewMark.Length).Trim()
      [void]$pre.Add([pscustomobject]@{ Path = $p; Expected = $null })
      continue
    }
    if ($l -match $reEntry) {
      [void]$pre.Add([pscustomobject]@{ Path = $Matches[2].Trim(); Expected = $Matches[1].ToLower() })
      continue
    }
    [void]$unparsed.Add($l)
  }

  if ($pre.Count -eq 0) {
    Write-Host '【清单不可解析】未能在《改动清单.txt》里找到「== 前像 sha256… ==」节的任何条目。'
    Write-Host '不套用任何文件。清单格式应为「<sha256>  <相对路径>」两列，或在新增文件行写「（新增，无前像）  <相对路径>」。'
    $script:ExitCode = 2
    return
  }
  if ($unparsed.Count -gt 0) {
    Write-Host ("【清单不可解析】前像节里有 {0} 行不符「<sha256>  <相对路径>」格式：" -f $unparsed.Count)
    foreach ($u in $unparsed) { Write-Host ("    " + $u) }
    Write-Host '不套用任何文件（宁可拒绝，也不在残缺清单上放行）。'
    $script:ExitCode = 2
    return
  }

  $preNew  = @($pre | Where-Object { $null -eq $_.Expected })
  $preMust = @($pre | Where-Object { $null -ne $_.Expected })
  Write-Host ("① 前像节：{0} 条（其中新增文件 {1} 条无前像、需校验 {2} 条）" -f $pre.Count, $preNew.Count, $preMust.Count)

  # ---- ② 逐条比对 --------------------------------------------------------
  $drift = New-Object System.Collections.ArrayList   # @{Path;Expected;Actual}
  $okCnt = 0
  foreach ($e in $preMust) {
    $t = Join-Path $root $e.Path
    if (-not (Test-Path -LiteralPath $t -PathType Leaf)) {
      [void]$drift.Add([pscustomobject]@{ Path = $e.Path; Expected = $e.Expected; Actual = $null })
      continue
    }
    $h = (Get-FileHash -LiteralPath $t -Algorithm SHA256).Hash.ToLower()
    if ($h -eq $e.Expected) { $okCnt++ }
    else { [void]$drift.Add([pscustomobject]@{ Path = $e.Path; Expected = $e.Expected; Actual = $h }) }
  }

  # ---- ③ 任一不符 ⇒ 立即停止，绝不套补丁 ---------------------------------
  if ($drift.Count -gt 0) {
    Write-Host ''
    Write-Host '【前像校验失败 · 已中止 · 未套用补丁】'
    Write-Host ("漂移文件 {0} / 需校验 {1} 个：" -f $drift.Count, $preMust.Count)
    foreach ($d in $drift) {
      $a = if ($null -eq $d.Actual) { '不存在' } else { $d.Actual }
      Write-Host ("    {0}" -f $d.Path)
      Write-Host ("        期望 sha256 : {0}" -f $d.Expected)
      Write-Host ("        实得 sha256 : {0}" -f $a)
    }
    Write-Host ''
    Write-Host '目标树不是本补丁的基线（上游可能已合并其它改动）；请重做基线或手工 rebase'
    $script:ExitCode = 2
    return
  }
  Write-Host ("   逐条相等：{0} / {0} 个文件（另有 {1} 个新增文件无前像，跳过）" -f $okCnt, $preNew.Count)
  Write-Host ''

  if (-not (Test-Path -LiteralPath $Git)) {
    Write-Host ("【git 不可用】找不到 git：{0}" -f $Git)
    Write-Host '不套用任何文件。'
    $script:ExitCode = 2
    return
  }

  # ---- ③.5 前置守卫：目标必须位于一个 git 工作树内 ------------------------
  # 实测（git 2.56.0.windows.2）：不在 git 仓里跑 `git apply` 会**逐条 Skipped 却仍退出 0**，
  # 于是「成功」是个空动作。这里宁可拒绝，也不放行一个什么都没干的 apply。
  # 说明：该判定按 git 的语义回答「这个目录是否在某个工作树内」——若目标本身没 .git 但其
  # 祖先目录有，git 会返回 true，此时由 ⑤.5 的「空动作自证」兜底拦下。
  $gr = GRun @('-C', $root, 'rev-parse', '--is-inside-work-tree')
  $isRepo = ([string]($gr.lines | Select-Object -First 1)).Trim()
  if ($gr.rc -ne 0 -or $isRepo -ne 'true') {
    Write-Host ("【目标不在 git 工作树内】{0}" -f $root)
    Write-Host 'git apply 在非 git 目录里会「逐条 Skipped 且退出 0」，即静默什么都不做；本脚本拒绝这种放行。'
    Write-Host '请先初始化（只建 .git，不动你的文件内容）：'
    Write-Host ("    git -C `"{0}`" init -q" -f $root)
    Write-Host '然后重跑本脚本。不套用任何文件。'
    $script:ExitCode = 2
    return
  }
  Write-Host '③ 目标位于 git 工作树内 —— 通过'
  Write-Host ''

  # ---- ④ git apply --check ----------------------------------------------
  Write-Host '④ git apply --check'
  $gr = GRun @('-C', $root, '-c', 'core.quotepath=false', '-c', 'core.autocrlf=false', '-c', 'core.safecrlf=false', 'apply', '--check', $patch)
  if ($gr.rc -ne 0) {
    Write-Host ("git apply --check 失败（退出码 {0}），git 原文如下：" -f $gr.rc)
    foreach ($o in $gr.lines) { Write-Host ([string]$o) }
    Write-Host ''
    Write-Host '【已中止 · 未套用补丁】目标树内容与补丁不匹配（逐字节级）。'
    $script:ExitCode = 1
    return
  }
  Write-Host '    --check 通过'
  Write-Host ''

  # ---- ④.5 记录补丁触及的每个文件的套用前状态 ---------------------------
  $patchText = [System.IO.File]::ReadAllText($patch, [System.Text.Encoding]::UTF8)
  $touched = New-Object System.Collections.ArrayList
  foreach ($line in ($patchText -split "`n")) {
    if ($line -match '^\+\+\+ b/(.+)$') {
      $p = $Matches[1].Trim()
      if ($p -ne '/dev/null' -and -not $touched.Contains($p)) { [void]$touched.Add($p) }
    }
  }
  $snap = @{}
  foreach ($p in $touched) {
    $t = Join-Path $root ($p -replace '/', '\')
    if (Test-Path -LiteralPath $t -PathType Leaf) {
      $snap[$p] = (Get-FileHash -LiteralPath $t -Algorithm SHA256).Hash.ToLower()
    } else {
      $snap[$p] = $null
    }
  }

  # ---- ⑤ git apply ------------------------------------------------------
  Write-Host '⑤ git apply'
  $gr = GRun @('-C', $root, '-c', 'core.quotepath=false', '-c', 'core.autocrlf=false', '-c', 'core.safecrlf=false', 'apply', $patch)
  if ($gr.rc -ne 0) {
    Write-Host ("git apply 失败（退出码 {0}），git 原文如下：" -f $gr.rc)
    foreach ($o in $gr.lines) { Write-Host ([string]$o) }
    Write-Host ''
    Write-Host '【套用失败】--check 曾通过但写入失败，目标树可能处于半套用状态，请人工检查。'
    $script:ExitCode = 1
    return
  }
  foreach ($o in $out) { Write-Host ([string]$o) }

  # ---- ⑤.5 自证：补丁触及的每个文件都必须真的变了 ------------------------
  $noop = New-Object System.Collections.ArrayList
  foreach ($p in $touched) {
    $t = Join-Path $root ($p -replace '/', '\')
    if (Test-Path -LiteralPath $t -PathType Leaf) {
      $after = (Get-FileHash -LiteralPath $t -Algorithm SHA256).Hash.ToLower()
    } else {
      $after = $null
    }
    if ($after -eq $snap[$p]) { [void]$noop.Add($p) }
  }
  if ($noop.Count -gt 0) {
    Write-Host ''
    Write-Host ("【git apply 是空动作】退出码虽是 0，但下列 {0} 个文件套用前后 sha256 不变：" -f $noop.Count)
    foreach ($p in $noop) { Write-Host ("    " + $p) }
    Write-Host '这意味着补丁其实没有被写进去：git apply 不在 git 工作树里会把 hunk 逐条 Skipped 却仍退出 0。'
    $gt = ([string](GRun @('-C', $root, 'rev-parse', '--show-toplevel')).lines | Select-Object -First 1).Trim()
    if ($gt -ne $root) {
      Write-Host ("目标自己不是工作树根（git 认为根是 {0}）；对它单独 git init 后重跑：" -f $gt)
      Write-Host ("    git -C `"{0}`" init -q" -f $root)
    }
    Write-Host '目标树可能已被部分改动，请人工检查；不视为套用成功。'
    $script:ExitCode = 1
    return
  }

  Write-Host ''
  Write-Host ("套用完成。（本脚本独立复核：补丁触及的 {0} 个文件套用前后 sha256 全部发生变化）" -f $touched.Count)
  Write-Host ''
  Write-Host '接着请跑下面 11 条（[1]–[10] 在目标仓根下跑；python 用交付环境内的解释器）：'
  $cmds = @(
    ('{0} -X utf8 scripts\review_build.py'                            -f $Py),
    ('{0} -X utf8 scripts\review_build.py --check'                    -f $Py),
    ('{0} -X utf8 scripts\review_build.py --rubric-report'            -f $Py),
    ('{0} -X utf8 scripts\evidence_probe.py --all'                    -f $Py),
    ('{0} -X utf8 scripts\evidence_check.py'                          -f $Py),
    ('{0} -X utf8 scripts\evidence_check.py --repro'                  -f $Py),
    ('{0} -X utf8 tests\test_review_build.py'                         -f $Py),
    ('{0} -X utf8 tests\test_review_build.py --mutate'                -f $Py),
    ('{0} -X utf8 tests\test_evidence_check.py'                       -f $Py),
    ('{0} -X utf8 tests\test_evidence_check.py --mutate'              -f $Py),
    ('{0} -X utf8 <交付包>\notes\verify_data.py   # [11] 第三份独立实现（脚本在交付包的 notes\ 下，不在仓内，故其路径指向交付包）' -f $Py)
  )
  for ($i = 0; $i -lt $cmds.Count; $i++) {
    Write-Host ("  [{0,2}] {1}" -f ($i + 1), $cmds[$i])
  }
  Write-Host ''
  Write-Host '期望：全部退出码 0（[1] 生成后 [2] --check 应报「产物与真源一致」）。'
  $script:ExitCode = 0
}
catch {
  Write-Host ''
  Write-Host ("【意外错误】{0}" -f $_.Exception.Message)
  Write-Host '不视为套用成功。'
  $script:ExitCode = 2
}
finally {
  exit $script:ExitCode
}
