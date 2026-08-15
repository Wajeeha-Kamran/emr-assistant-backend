<#
  Generates synthetic consultation audio using the speech voices built into
  Windows. Offline, free, no account, no download.

  WHY THIS EXISTS
  Diarization measured 35.9% - 64.1% mean speaker accuracy on the four human
  recordings (15 Aug 2026), depending only on which cluster was named DOCTOR.
  Reading the labelled transcripts showed pyannote merging the two voices on
  three of the four recordings: both speakers were recorded by two family
  members of similar age and accent, which is the hardest case for speaker
  separation.

  That leaves two explanations that the human recordings cannot tell apart:

      (a) the pipeline is wrong
      (b) the pipeline is right and the two voices were too similar

  This script produces the control condition. The same scripted words are
  spoken by two deliberately dissimilar voices (one male, one female). If
  accuracy is high here and low on the human recordings, (b) is established
  and the limitation is acoustic, not a defect in the implementation.

  The synthetic set is a CONTROL, not a replacement. The human recordings
  remain the reported result. Reporting synthetic numbers as though they were
  real-world performance would be dishonest: this audio has no overlapping
  speech, no background noise and no natural disfluency.

  Usage, from the repository root:
      powershell -ExecutionPolicy Bypass -File scripts\synthesize_scripts.ps1
  Then:
      .\.venv\Scripts\python.exe -m scripts.build_synthetic_audio
#>

$ErrorActionPreference = "Stop"

$scriptsMd = "docs\evidence\consultation_scripts.md"
$partsDir  = "docs\evidence\synthetic\parts"

if (-not (Test-Path $scriptsMd)) {
    throw "Cannot find $scriptsMd. Run this from the repository root."
}
New-Item -ItemType Directory -Force -Path $partsDir | Out-Null
Get-ChildItem -Path $partsDir -Filter *.wav -ErrorAction SilentlyContinue | Remove-Item -Force

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

$voices = $synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo }
Write-Host "Installed voices:"
foreach ($v in $voices) { Write-Host ("  {0}  ({1})" -f $v.Name, $v.Gender) }

# Two voices of different gender are chosen deliberately. The whole point of
# the control is maximum acoustic separation; picking two similar voices would
# reproduce the very problem being isolated.
$male   = $voices | Where-Object { $_.Gender -eq "Male" }   | Select-Object -First 1
$female = $voices | Where-Object { $_.Gender -eq "Female" } | Select-Object -First 1

if (-not $male -or -not $female) {
    throw ("Need one male and one female voice; found: " +
           (($voices | ForEach-Object { $_.Name + '/' + $_.Gender }) -join ', ') +
           ". Add voices under Settings > Time & Language > Speech.")
}

$doctorVoice  = $male.Name
$patientVoice = $female.Name
Write-Host ""
Write-Host ("DOCTOR  -> {0}" -f $doctorVoice)
Write-Host ("PATIENT -> {0}" -f $patientVoice)
Write-Host ""

$script = 0
$turn   = 0
$made   = 0

foreach ($line in Get-Content $scriptsMd -Encoding UTF8) {

    # Same section regex the evaluation script uses, so the audio and the
    # reference text can never drift apart.
    if ($line -match '^##\s*Script\s+(\d+)') {
        $script = [int]$Matches[1]
        $turn = 0
        continue
    }
    if ($script -eq 0) { continue }

    if ($line -match '^(DOCTOR|PATIENT):\s*(.+?)\s*$') {
        $speaker = $Matches[1]
        $text    = $Matches[2]
        $turn++

        $voice = if ($speaker -eq "DOCTOR") { $doctorVoice } else { $patientVoice }
        $out = Join-Path $partsDir ("s{0}_t{1:d2}_{2}.wav" -f $script, $turn, $speaker)

        $synth.SelectVoice($voice)
        $synth.SetOutputToWaveFile($out)
        $synth.Speak($text)
        $made++
    }
}

$synth.SetOutputToDefaultAudioDevice()
$synth.Dispose()

Write-Host ("Wrote {0} turn files to {1}" -f $made, $partsDir)
Write-Host "Next: .\.venv\Scripts\python.exe -m scripts.build_synthetic_audio"
