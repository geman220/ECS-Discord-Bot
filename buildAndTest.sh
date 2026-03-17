#!/bin/bash
# ECS Discord Bot & WebUI - Build and Test Script (Mac/Linux)

# Exit on any error
set -e

echo "🚀 Starting Build and Test process..."

# 1. Bot Core Tests
echo ""
echo "========================================"
echo "--- Running Bot Core Unit Tests ---"
echo "========================================"
export PYTHONPATH=$PYTHONPATH:.
python3 -m pytest tests/

# 2. WebUI Python Tests
# echo ""
# echo "========================================"
# echo "--- Running WebUI Python Tests ---"
# echo "========================================"
# cd Discord-Bot-WebUI
# if [ -f "run_tests.py" ]; then
#     python3 run_tests.py --unit --integration
# else
#     echo "⚠️ run_tests.py not found in Discord-Bot-WebUI/"
# fi

# 3. WebUI Frontend Tests
# echo ""
# echo "========================================"
# echo "--- Running WebUI Frontend Tests ---"
# echo "========================================"
# if [ -f "package.json" ]; then
#     # Check if node_modules exists, if not install
#     if [ ! -d "node_modules" ]; then
#         echo "📦 node_modules not found, running npm install..."
#         npm install
#     fi
#     npm test
# else
#     echo "⚠️ package.json not found in Discord-Bot-WebUI/"
# fi

cd ..
echo ""
echo "✅ All tests passed successfully!"
