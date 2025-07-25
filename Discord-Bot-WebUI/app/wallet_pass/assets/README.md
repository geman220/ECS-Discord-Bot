# Apple Wallet Pass Assets

This directory should contain the required image assets for your Apple Wallet passes.

## Required Image Files

Place the following image files in this directory:

### Icons (Required)
- **icon.png** - 29×29 pixels, PNG format
- **icon@2x.png** - 58×58 pixels, PNG format (high-resolution)

### Logos (Required)
- **logo.png** - Maximum 160×50 pixels, PNG format
- **logo@2x.png** - Maximum 320×100 pixels, PNG format (high-resolution)

## Image Requirements

### General Guidelines
- **Format**: PNG only
- **Color Space**: sRGB
- **Compression**: Optimized for file size
- **Quality**: High resolution for best appearance

### Icon Images
- **Size**: Exactly 29×29 and 58×58 pixels
- **Transparency**: Not recommended for icons
- **Design**: Simple, recognizable symbol
- **Usage**: Displayed in Wallet app and notifications

### Logo Images
- **Size**: Maximum 160×50 (1x) and 320×100 (2x) pixels
- **Transparency**: Allowed and recommended for logo
- **Design**: Your organization logo
- **Usage**: Displayed on the pass itself

## Design Tips

1. **Keep it Simple**: Icons should be easily recognizable at small sizes
2. **High Contrast**: Ensure good visibility on different backgrounds
3. **Brand Consistent**: Use your official brand colors and fonts
4. **Test on Device**: Always test how assets look on actual iOS devices

## Sample Assets

For ECS FC, consider:
- **Icon**: Soccer ball, team crest, or "ECS" initials
- **Logo**: Full ECS FC logo or wordmark

## File Optimization

Optimize your images for the best file size:

```bash
# Using ImageOptim (macOS)
imageoptim icon.png icon@2x.png logo.png logo@2x.png

# Using pngcrush
pngcrush -brute original.png optimized.png
```

## Validation

Apple Wallet will reject passes with:
- Missing required assets
- Incorrect image dimensions
- Unsupported file formats
- Corrupted image files

Test your passes on an actual iOS device to ensure assets display correctly.

See WALLET_SETUP.md for complete setup instructions.