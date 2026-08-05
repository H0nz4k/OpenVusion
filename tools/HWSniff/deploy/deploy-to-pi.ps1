<#
.SYNOPSIS
  Deploy HWSniff GPIO to a Raspberry Pi over SSH (no manual USB/copy).

.DESCRIPTION
  Modes:
    Quick (default) - sync tools/HWSniff code into /opt/Sniff and restart service
    Full            - pack bundle, upload, run install-on-pi.sh --no-start

  Prerequisites on Windows: OpenSSH client (scp, ssh), Python 3.
  On the Pi: first Full install once; then use Quick for daily updates.

.EXAMPLE
  .\deploy-to-pi.ps1 -Target sniffer@192.168.1.4

.EXAMPLE
  .\deploy-to-pi.ps1 -Target sniffer@192.168.1.4 -Mode Full

.EXAMPLE
  # After creating deploy.env with HWSNIFF_PI=...
  .\deploy-to-pi.ps1
#>
[CmdletBinding()]
param(
    [string] $Target = "",
    [ValidateSet("Quick", "Full")]
    [string] $Mode = "Quick",
    [switch] $NoRestart,
    [switch] $SkipPack,
    [string] $SshOpts = ""
)

$ErrorActionPreference = "Stop"

$DeployDir = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $DeployDir "..\..\..")).Path
$HwsniffRoot = (Resolve-Path (Join-Path $DeployDir "..")).Path
$EnvFile = Join-Path $DeployDir "deploy.env"

function Read-DeployEnv {
    if (-not (Test-Path $EnvFile)) { return }
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            $name = $Matches[1]
            $val = $Matches[2].Trim().Trim('"').Trim("'")
            Set-Item -Path "Env:$name" -Value $val
        }
    }
}

function Assert-Command([string] $Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing command '$Name'. Install OpenSSH Client (Windows Optional Features) / Python."
    }
}

function Invoke-Ssh([string] $RemoteCmd) {
    $sshArgs = @()
    if ($script:SshExtra) { $sshArgs += $script:SshExtra }
    $sshArgs += @("-o", "StrictHostKeyChecking=accept-new", $script:Target, $RemoteCmd)
    & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) {
        if ($LASTEXITCODE -eq 255) {
            throw @"
SSH login failed for $($script:Target) (exit 255).

Check:
  1) Can you log in manually?  ssh $($script:Target)
  2) Username should be 'sniffer' (not 'pi').
  3) Wrong password, or only SSH keys allowed.
  4) Try: .\deploy-to-pi.ps1 -Target sniffer@192.168.1.4 -Mode Full

Failed command: $RemoteCmd
"@
        }
        throw "ssh failed (exit $LASTEXITCODE): $RemoteCmd"
    }
}

function Invoke-Scp([string[]] $ScpArgs) {
    $all = @()
    if ($script:SshExtra) { $all += $script:SshExtra }
    $all += $ScpArgs
    & scp @all
    if ($LASTEXITCODE -ne 0) { throw "scp failed (exit $LASTEXITCODE)" }
}

Read-DeployEnv

if (-not $Target) {
    if ($env:HWSNIFF_PI) { $Target = $env:HWSNIFF_PI }
}
if (-not $Target) {
    throw "Missing target. Use -Target sniffer@192.168.1.4 or set HWSNIFF_PI in deploy.env (see deploy.env.example)."
}

if (-not $SshOpts -and $env:HWSNIFF_SSH_OPTS) {
    $SshOpts = $env:HWSNIFF_SSH_OPTS
}

$script:SshExtra = @()
if ($SshOpts) {
    $script:SshExtra = $SshOpts.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
}
$script:Target = $Target

Assert-Command "ssh"
Assert-Command "scp"
Assert-Command "python"

Write-Host "==> Target : $Target"
Write-Host "==> Mode   : $Mode"
Write-Host "==> Repo   : $RepoRoot"

if ($Mode -eq "Full") {
    $distDir = Join-Path $DeployDir "dist"
    if (-not $SkipPack) {
        Write-Host "==> Packing bundle..."
        Push-Location $RepoRoot
        try {
            python (Join-Path $DeployDir "pack_gpio_bundle.py")
        } finally {
            Pop-Location
        }
    }

    if (-not (Test-Path $distDir)) {
        throw "Dist folder missing: $distDir"
    }

    $tar = Get-ChildItem -Path $distDir -Filter "hwsniff-gpio-*.tar.gz" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $tar) {
        throw "No hwsniff-gpio-*.tar.gz in $distDir - run pack first."
    }

    $remoteDir = "~/hwsniff-deploy"
    Write-Host "==> Upload $($tar.Name)..."
    Invoke-Ssh "mkdir -p $remoteDir"
    Invoke-Scp @("-q", $tar.FullName, "${Target}:${remoteDir}/")

    $bundleName = $tar.Name
    if ($tar.Name -match '^(hwsniff-gpio-.+)\.tar\.gz$') {
        $bundleName = $Matches[1]
    }

    Write-Host "==> Remote extract + install-on-pi.sh --no-start..."
    $tarName = $tar.Name
    $remote = "set -euo pipefail; cd $remoteDir; rm -rf '$bundleName'; tar -xzf '$tarName'; cd '$bundleName'; sudo bash install-on-pi.sh --no-start; echo DONE_FULL_INSTALL"
    Invoke-Ssh $remote
    Write-Host ""
    Write-Host "Full install finished (service DISABLED)."
    Write-Host "On Pi: sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --gpio-test"
    Write-Host "Then:  sudo systemctl enable --now hwsniff"
    return
}

# --- Quick mode --------------------------------------------------------------
$stage = Join-Path $env:TEMP ("hwsniff-quick-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    Write-Host "==> Staging HWSniff tree..."
    $null = robocopy $HwsniffRoot $stage /E /XD .venv __pycache__ .git deploy\dist captures /XF *.pyc /NFL /NDL /NJH /NJS /nc /ns /np
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed (exit $LASTEXITCODE)" }

    # Quick used to skip ElaTool -> CollectorConfig lagged behind HWSniff.
    $elaSrc = Join-Path $RepoRoot "tools\ElaTool"
    $elaDst = Join-Path $stage "_vendor\ElaTool"
    if (Test-Path (Join-Path $elaSrc "src\elatec_uid_tool")) {
        Write-Host "==> Staging ElaTool vendor..."
        New-Item -ItemType Directory -Path $elaDst -Force | Out-Null
        $null = robocopy $elaSrc $elaDst /E /XD .venv __pycache__ .git captures dist build *.egg-info /XF *.pyc /NFL /NDL /NJH /NJS /nc /ns /np
        if ($LASTEXITCODE -ge 8) { throw "robocopy ElaTool failed (exit $LASTEXITCODE)" }
    } else {
        Write-Warning "ElaTool source missing at $elaSrc - Pi vendor will not be updated"
    }

    $helperSrc = Join-Path $DeployDir "remote-quick-update.sh"
    $helperDst = Join-Path $stage "remote-quick-update.sh"
    $text = [System.IO.File]::ReadAllText($helperSrc) -replace "`r`n", "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($helperDst, $text, $utf8NoBom)

    $remoteTmp = "/tmp/hwsniff-quick"
    $stageName = Split-Path $stage -Leaf
    Write-Host "==> Upload to ${Target}:/tmp/$stageName -> $remoteTmp ..."
    Invoke-Ssh "rm -rf /tmp/$stageName $remoteTmp"
    Invoke-Scp @("-q", "-r", $stage, "${Target}:/tmp/")
    Invoke-Ssh "mv /tmp/$stageName $remoteTmp"

    $restart = if ($NoRestart) { "0" } else { "1" }
    Write-Host "==> Remote quick update (restart=$restart)..."
    Invoke-Ssh "sudo RESTART=$restart bash $remoteTmp/remote-quick-update.sh $remoteTmp"

    Write-Host ""
    Write-Host "Quick deploy done."
    Write-Host "Logs: ssh $Target journalctl -u hwsniff -n 40 --no-pager"
} finally {
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
}
