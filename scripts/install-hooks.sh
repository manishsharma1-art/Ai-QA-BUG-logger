#!/bin/sh
cp scripts/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo "Git pre-commit hook installed successfully."
