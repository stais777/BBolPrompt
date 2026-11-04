# Offline HWPX structural collection. Built-in Windows PowerShell/.NET only.
# Reads the original with FileAccess.Read. Does not extract or copy BinData assets.
# Windows execution has NOT been performed in the Linux development environment.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateNotNullOrEmpty()]
    [string]$SourcePath,
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
Add-Type -AssemblyName System.IO.Compression

function Get-StreamSha256([System.IO.Stream]$Stream) {
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($Hasher.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant()
    }
    finally { $Hasher.Dispose() }
}

function Get-SectionStructure([System.IO.Compression.ZipArchiveEntry]$Entry) {
    $Settings = New-Object System.Xml.XmlReaderSettings
    $Settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $Settings.XmlResolver = $null
    $Settings.MaxCharactersInDocument = 67108864
    $InputStream = $Entry.Open()
    $Reader = $null
    try {
        $Reader = [System.Xml.XmlReader]::Create($InputStream, $Settings)
        $ParagraphCount = 0
        $ImageRefCount = 0
        $PageBreakCount = 0
        $TableRowCount = 0
        $TextElementCount = 0
        while ($Reader.Read()) {
            if ($Reader.NodeType -ne [System.Xml.XmlNodeType]::Element) { continue }
            switch ($Reader.LocalName.ToLowerInvariant()) {
                'p' { $ParagraphCount++ }
                'tr' { $TableRowCount++ }
                't' { $TextElementCount++ }
            }
            if ($Reader.HasAttributes) {
                while ($Reader.MoveToNextAttribute()) {
                    $AttributeName = $Reader.LocalName.ToLowerInvariant()
                    if ($AttributeName -eq 'binaryitemidref') { $ImageRefCount++ }
                    if ($AttributeName -eq 'pagebreak' -and $Reader.Value -match '^(?i:1|true)$') { $PageBreakCount++ }
                }
                [void]$Reader.MoveToElement()
            }
        }
        return [ordered]@{
            path = $Entry.FullName
            paragraph_elements = $ParagraphCount
            image_reference_attributes = $ImageRefCount
            explicit_page_break_attributes = $PageBreakCount
            table_row_elements = $TableRowCount
            text_elements = $TextElementCount
        }
    }
    finally {
        if ($null -ne $Reader) { $Reader.Dispose() }
        $InputStream.Dispose()
    }
}

$SourceStream = $null
$Archive = $null
$DestinationStream = $null
$DestinationArchive = $null
$TemporaryOutput = $null
try {
    $ResolvedSource = (Resolve-Path -LiteralPath $SourcePath -ErrorAction Stop).ProviderPath
    if (-not [IO.File]::Exists($ResolvedSource) -or [IO.Path]::GetExtension($ResolvedSource) -ine '.hwpx') {
        throw 'Select an existing .hwpx file.'
    }
    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
        $OutputDirectory = [Environment]::GetFolderPath('Desktop')
        if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = [IO.Path]::GetTempPath() }
    }
    [void][IO.Directory]::CreateDirectory($OutputDirectory)
    $OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).ProviderPath
    $Suffix = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
    $FinalOutput = Join-Path $OutputDirectory ('Bbolprom-structure-' + $Suffix + '.zip')
    $TemporaryOutput = Join-Path $OutputDirectory ('.Bbolprom-structure-' + $Suffix + '.tmp')

    # A read-only handle with FileShare.Read also prevents a concurrent writer
    # from changing the input between the SHA256 calculation and XML copying.
    $SourceStream = [IO.File]::Open($ResolvedSource, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    Write-Output 'Reading the original HWPX SHA256. Large input may take a moment.'
    $SourceSha256 = Get-StreamSha256 $SourceStream
    $SourceBytes = $SourceStream.Length
    $SourceStream.Position = 0
    $Archive = New-Object System.IO.Compression.ZipArchive($SourceStream, [IO.Compression.ZipArchiveMode]::Read, $true)
    if ($Archive.Entries.Count -gt 30000) { throw 'ZIP entry count exceeds 30000.' }

    $Manifest = New-Object System.Collections.Generic.List[object]
    $Selected = New-Object System.Collections.Generic.List[System.IO.Compression.ZipArchiveEntry]
    $SectionReports = New-Object System.Collections.Generic.List[object]
    $SeenNames = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $TotalXmlBytes = [long]0
    foreach ($Entry in $Archive.Entries) {
        $Name = $Entry.FullName.Replace('\', '/')
        if ($Name.EndsWith('/')) { continue }
        if ($Name.StartsWith('/') -or $Name -match '(^|/)\.\.(/|$)' -or $Name.Contains(':')) {
            throw 'Unsafe ZIP member name encountered.'
        }
        if (-not $SeenNames.Add($Name)) { throw 'Duplicate/case-colliding ZIP member name encountered.' }
        # Strict text/metadata allowlist; never include images, previews or media.
        $Include = ($Name -match '^(?i:Contents/.*\.xml|Contents/content\.hpf|META-INF/.*\.xml|version\.xml|mimetype)$')
        $Manifest.Add([ordered]@{
            path = $Name
            bytes = $Entry.Length
            compressed_bytes = $Entry.CompressedLength
            copied = [bool]$Include
        })
        if ($Include) {
            if ($Entry.Length -gt 67108864) { throw 'A selected XML/metadata member exceeds 64 MiB.' }
            $TotalXmlBytes += $Entry.Length
            if ($TotalXmlBytes -gt 268435456) { throw 'Selected XML/metadata exceeds 256 MiB total.' }
            $Selected.Add($Entry)
            if ($Name -match '(?i)(^|/)section\d+\.xml$') {
                $SectionReports.Add((Get-SectionStructure $Entry))
            }
        }
    }
    if ($SectionReports.Count -eq 0) { throw 'No sectionN.xml found. The input is not a supported HWPX document.' }
    if ($SectionReports.Count -gt 512) { throw 'More than 512 sections found.' }

    Write-Output ('Copying XML/metadata only: ' + $Selected.Count + ' members.')
    $DestinationStream = [IO.File]::Open($TemporaryOutput, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $DestinationArchive = New-Object System.IO.Compression.ZipArchive($DestinationStream, [IO.Compression.ZipArchiveMode]::Create, $true)
    $Copied = New-Object System.Collections.Generic.List[object]
    foreach ($Entry in $Selected) {
        $NewEntry = $DestinationArchive.CreateEntry($Entry.FullName.Replace('\','/'), [IO.Compression.CompressionLevel]::Optimal)
        $Input = $Entry.Open()
        $Output = $NewEntry.Open()
        try { $Input.CopyTo($Output) }
        finally { $Output.Dispose(); $Input.Dispose() }
        $HashInput = $Entry.Open()
        try { $EntrySha256 = Get-StreamSha256 $HashInput }
        finally { $HashInput.Dispose() }
        $Copied.Add([ordered]@{ path = $Entry.FullName.Replace('\','/'); bytes = $Entry.Length; sha256 = $EntrySha256 })
    }
    $Report = [ordered]@{
        schema = 'bbolprom-hwpx-structure-diagnostic-1'
        generated_utc = [DateTime]::UtcNow.ToString('o')
        source_name = [IO.Path]::GetFileName($ResolvedSource)
        source_bytes = $SourceBytes
        source_sha256 = $SourceSha256
        expected_actual_pt_sha256 = 'c5d52ce0cda5901d9da178f88c8d5c2eeb5614eefa5a0546916e4951df881ddf'
        actual_pt_sha_matches = ($SourceSha256 -eq 'c5d52ce0cda5901d9da178f88c8d5c2eeb5614eefa5a0546916e4951df881ddf')
        collection = 'Unmodified XML/metadata only; BinData and preview image entries omitted.'
        limitations = @('No source image bytes; no image pixel or original-image hash validation.', 'Card boundaries are not inferred by this collector.', 'This diagnostic ZIP is not a replacement for the original HWPX.', 'Raw XML retains prompt text and any inline content originally stored in XML.')
        sections = @($SectionReports.ToArray())
        copied_members = @($Copied.ToArray())
        source_archive_members = @($Manifest.ToArray())
    }
    $ReportEntry = $DestinationArchive.CreateEntry('_diagnostics/structure-report.json', [IO.Compression.CompressionLevel]::Optimal)
    $ReportStream = $ReportEntry.Open()
    $Utf8 = New-Object System.Text.UTF8Encoding($false)
    try {
        $ReportBytes = $Utf8.GetBytes(($Report | ConvertTo-Json -Depth 12))
        $ReportStream.Write($ReportBytes,0,$ReportBytes.Length)
    }
    finally { $ReportStream.Dispose() }
    $DestinationArchive.Dispose(); $DestinationArchive = $null
    $DestinationStream.Dispose(); $DestinationStream = $null
    [IO.File]::Move($TemporaryOutput,$FinalOutput)
    $TemporaryOutput = $null
    $FinalStream = [IO.File]::OpenRead($FinalOutput)
    try { $OutputHash = Get-StreamSha256 $FinalStream }
    finally { $FinalStream.Dispose() }
    Write-Output ('Created: ' + $FinalOutput)
    Write-Output ('ZIP bytes: ' + (Get-Item -LiteralPath $FinalOutput).Length)
    Write-Output ('ZIP SHA256: ' + $OutputHash)
    Write-Output 'Attach this diagnostic ZIP to the chat. The original HWPX was not modified.'
    exit 0
}
catch {
    Write-Error -Message ('Collection failed: ' + $_.Exception.Message) -ErrorAction Continue
    exit 1
}
finally {
    if ($null -ne $DestinationArchive) { $DestinationArchive.Dispose() }
    if ($null -ne $DestinationStream) { $DestinationStream.Dispose() }
    if ($null -ne $Archive) { $Archive.Dispose() }
    if ($null -ne $SourceStream) { $SourceStream.Dispose() }
    if ($null -ne $TemporaryOutput -and [IO.File]::Exists($TemporaryOutput)) { [IO.File]::Delete($TemporaryOutput) }
}
