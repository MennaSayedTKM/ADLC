# One-time setup of Pulumi's own storage inside the ADLC AWS account:
#   - an S3 bucket for Pulumi state (versioned, public access blocked)
#   - a KMS key that encrypts the stack's secrets (OpenAI key, ...)
# then logs Pulumi in to that bucket and creates/selects the "prod" stack.
# Safe to re-run. Run from the repo root after `aws sso login --profile adlc`:
#
#   powershell -ExecutionPolicy Bypass -File infra\bootstrap.ps1

param(
    [string]$AwsProfile = "adlc",
    [string]$Region = "eu-central-1",
    [string]$Stack = "prod"
)

function Invoke-Aws {
    # Runs the AWS CLI; returns $true on success. Output is kept in $script:AwsOut.
    $script:AwsOut = & aws @args --profile $AwsProfile 2>&1
    return ($LASTEXITCODE -eq 0)
}

if (-not (Invoke-Aws sts get-caller-identity --query Account --output text)) {
    Write-Error "Not logged in. Run: aws sso login --profile $AwsProfile"; exit 1
}
$account = "$script:AwsOut".Trim()
Write-Host "AWS account: $account  region: $Region"

# --- State bucket -------------------------------------------------------------
$bucket = "adlc-pulumi-state-$account"
if (Invoke-Aws s3api head-bucket --bucket $bucket) {
    Write-Host "State bucket exists: $bucket"
} else {
    if (-not (Invoke-Aws s3api create-bucket --bucket $bucket --region $Region `
            --create-bucket-configuration "LocationConstraint=$Region")) {
        Write-Error "Could not create bucket ${bucket}: $script:AwsOut"; exit 1
    }
    Write-Host "Created state bucket: $bucket"
}
# New S3 buckets are already encrypted (SSE-S3) by default.
Invoke-Aws s3api put-bucket-versioning --bucket $bucket --versioning-configuration Status=Enabled | Out-Null
Invoke-Aws s3api put-public-access-block --bucket $bucket --public-access-block-configuration `
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" | Out-Null

# --- Secrets key --------------------------------------------------------------
$alias = "alias/adlc-pulumi"
if (Invoke-Aws kms describe-key --key-id $alias --region $Region) {
    Write-Host "Secrets key exists: $alias"
} else {
    if (-not (Invoke-Aws kms create-key --description "Encrypts ADLC Pulumi stack secrets" `
            --region $Region --query KeyMetadata.KeyId --output text)) {
        Write-Error "Could not create KMS key: $script:AwsOut"; exit 1
    }
    $keyId = "$script:AwsOut".Trim()
    Invoke-Aws kms create-alias --alias-name $alias --target-key-id $keyId --region $Region | Out-Null
    Invoke-Aws kms enable-key-rotation --key-id $keyId --region $Region | Out-Null
    Write-Host "Created secrets key: $alias"
}

# --- Pulumi login + stack -----------------------------------------------------
Push-Location (Join-Path $PSScriptRoot ".")
try {
    pulumi login "s3://${bucket}?region=${Region}&awssdk=v2&profile=${AwsProfile}"
    if ($LASTEXITCODE -ne 0) { exit 1 }
    pulumi stack select $Stack --create `
        --secrets-provider "awskms://${alias}?region=${Region}&awssdk=v2&profile=${AwsProfile}"
    if ($LASTEXITCODE -ne 0) { exit 1 }
    Write-Host ""
    Write-Host "Done. Next (from infra\):"
    Write-Host "  pulumi install"
    Write-Host "  pulumi config set --secret adlc:openaiApiKey"
    Write-Host "  pulumi preview"
} finally {
    Pop-Location
}
