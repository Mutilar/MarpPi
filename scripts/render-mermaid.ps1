param(
    [string]$InputPath = (Join-Path $PSScriptRoot "..\readme.md"),
    [string]$OutputPath = (Join-Path $PSScriptRoot "..\assets\diagrams\high-level-wiring.png"),
    [int]$DiagramIndex = 0,
    [switch]$AllReadmes,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "..\assets\diagrams")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Throw-IfMissingCommand {
    param([string]$CommandName)
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "Required command '$CommandName' was not found. Install Node.js from https://nodejs.org/ to gain access to npx."
    }
}

function Get-RepositoryRoot {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Resolve-OutputPath {
    param(
        [string]$RelativeOrAbsolutePath,
        [string]$RepoRoot
    )

    if ([System.IO.Path]::IsPathRooted($RelativeOrAbsolutePath)) {
        return [System.IO.Path]::GetFullPath($RelativeOrAbsolutePath)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $RelativeOrAbsolutePath))
}

function Get-MermaidBlocks {
    param([string]$MarkdownPath)

    $content = Get-Content -Path $MarkdownPath -Raw
    if ($null -eq $content) {
        return @()
    }
    $regex = [regex]'```mermaid\s+([\s\S]*?)```'
    $matches = $regex.Matches($content)

    $metaRegex = [regex]'<!--\s*mermaid-output\s*:\s*(.*?)\s*-->'
    $metaMatches = $metaRegex.Matches($content)
    $metaQueue = New-Object System.Collections.Generic.Queue[System.Text.RegularExpressions.Match]
    foreach ($meta in $metaMatches) {
        $metaQueue.Enqueue($meta)
    }

    $blocks = @()
    for ($i = 0; $i -lt $matches.Count; $i++) {
        $match = $matches[$i]
        $outputPath = $null

        while ($metaQueue.Count -gt 0 -and $metaQueue.Peek().Index -lt $match.Index) {
            $outputPath = $metaQueue.Dequeue().Groups[1].Value.Trim()
        }

        $blocks += [pscustomobject]@{
            Index = $i
            Source = $match.Groups[1].Value.Trim()
            OutputPath = $outputPath
            MarkdownPath = $MarkdownPath
        }
    }

    return $blocks
}

function Get-MermaidCliPath {
    param([string]$RepoRoot)

    $binDir = Join-Path $RepoRoot "node_modules/.bin"
    $candidates = @("mmdc.cmd", "mmdc.ps1", "mmdc")

    foreach ($candidate in $candidates) {
        $resolved = Join-Path $binDir $candidate
        if (Test-Path -Path $resolved) {
            return $resolved
        }
    }

    return $null
}

function Render-MermaidBlock {
    param(
        [string]$DiagramSource,
        [string]$AbsoluteOutputPath,
        [string]$RepoRoot
    )

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "marp-mermaid"
    if (-not (Test-Path -Path $tempRoot)) {
        New-Item -ItemType Directory -Path $tempRoot | Out-Null
    }

    $tempFile = Join-Path $tempRoot "diagram.mmd"
    $DiagramSource | Set-Content -Path $tempFile -Encoding utf8

    $fullOutputPath = [System.IO.Path]::GetFullPath($AbsoluteOutputPath)
    $outputDirectory = Split-Path -Parent $fullOutputPath
    if (-not (Test-Path -Path $outputDirectory)) {
        New-Item -ItemType Directory -Path $outputDirectory | Out-Null
    }

    $localCli = $null
    if ($RepoRoot) {
        $localCli = Get-MermaidCliPath -RepoRoot $RepoRoot
    }

    if ($localCli) {
        & $localCli "-i" $tempFile "-o" $fullOutputPath
    } else {
        Throw-IfMissingCommand -CommandName "npx"
        $arguments = @("--yes", "-p", "@mermaid-js/mermaid-cli", "--", "mmdc", "-i", $tempFile, "-o", $fullOutputPath)
        & npx @arguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Mermaid CLI exited with code $LASTEXITCODE."
    }

    Write-Host "Rendered diagram saved to $fullOutputPath"
}

$repoRoot = Get-RepositoryRoot

if ($AllReadmes) {
    Throw-IfMissingCommand -CommandName "npx"
    $readmeFiles = Get-ChildItem -Path $repoRoot -Filter "README*.md" -Recurse -File |
        Where-Object { $_.FullName -notmatch "\\node_modules\\" -and $_.FullName -notmatch "\\.git\\" }

    foreach ($file in $readmeFiles) {
        $blocks = Get-MermaidBlocks -MarkdownPath $file.FullName
        if (-not $blocks) {
            continue
        }

        foreach ($block in @($blocks)) {
            if (-not $block.OutputPath) {
                throw "No mermaid-output comment found in '$($block.MarkdownPath)' for diagram index $($block.Index). Add <!-- mermaid-output: relative/path.png --> before the code block."
            }

            $absoluteOutputPath = Resolve-OutputPath -RelativeOrAbsolutePath $block.OutputPath -RepoRoot $repoRoot
            Write-Host "Rendering $($file.FullName) diagram #$($block.Index) -> $absoluteOutputPath"
            Render-MermaidBlock -DiagramSource $block.Source -AbsoluteOutputPath $absoluteOutputPath -RepoRoot $repoRoot
        }
    }

    return
}

if (-not (Test-Path -Path $InputPath)) {
    throw "Could not locate input markdown file at '$InputPath'."
}

$blocks = Get-MermaidBlocks -MarkdownPath $InputPath
$blocks = @($blocks)

if ($blocks.Count -eq 0) {
    throw "No mermaid code block was found in '$InputPath'."
}

if ($DiagramIndex -lt 0 -or $DiagramIndex -ge $blocks.Count) {
    throw "DiagramIndex $DiagramIndex is out of range. Found $($blocks.Count) mermaid block(s)."
}

$selected = $blocks[$DiagramIndex]
$targetOutputPath = $null

if ($PSBoundParameters.ContainsKey('OutputPath')) {
    $targetOutputPath = Resolve-OutputPath -RelativeOrAbsolutePath $OutputPath -RepoRoot $repoRoot
} elseif ($selected.OutputPath) {
    $targetOutputPath = Resolve-OutputPath -RelativeOrAbsolutePath $selected.OutputPath -RepoRoot $repoRoot
} else {
    throw "No output path provided. Specify -OutputPath or add <!-- mermaid-output: relative/path.png --> before the mermaid block."
}

Render-MermaidBlock -DiagramSource $selected.Source -AbsoluteOutputPath $targetOutputPath -RepoRoot $repoRoot
