# Apple Wallet Certificates

This directory should contain your Apple Developer certificates for signing wallet passes.

## Required Files

Place the following files in this directory:

- **certificate.pem** - Your Pass Type ID certificate (PEM format)
- **key.pem** - Your private key (PEM format)
- **wwdr.pem** - Apple WWDR certificate (PEM format)

## Security Notice

⚠️ **IMPORTANT**: These certificate files contain sensitive cryptographic material.

- **Never commit these files to version control**
- Restrict file permissions (chmod 600)
- Store securely with backup
- Rotate certificates before expiration

## Certificate Conversion

If you have PKCS12 files from Apple Developer Portal, convert them using:

```bash
# Convert certificate (you'll be prompted for password)
openssl pkcs12 -in "Certificates.p12" -clcerts -nokeys -out certificate.pem

# Convert private key
openssl pkcs12 -in "Certificates.p12" -nocerts -out key.pem

# Download and convert Apple WWDR certificate
wget https://www.apple.com/certificateauthority/AppleWWDRCAG3.cer
openssl x509 -inform DER -in AppleWWDRCAG3.cer -out wwdr.pem
```

## File Verification

You can verify your certificates using:

```bash
# Check certificate details
openssl x509 -in certificate.pem -text -noout

# Verify private key
openssl rsa -in key.pem -check

# Check Apple WWDR certificate
openssl x509 -in wwdr.pem -text -noout
```