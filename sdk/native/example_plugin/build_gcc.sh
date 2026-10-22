#!/bin/sh
# Linux / macOS / MinGW-w64 构建示例。
set -e
cd "$(dirname "$0")"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) gcc -shared -O2 -Wall -Wextra -I.. plugin.c -o plugin.dll ;;
  Darwin*) clang -dynamiclib -O2 -Wall -Wextra -I.. plugin.c -o plugin.dylib ;;
  *) gcc -shared -fPIC -O2 -Wall -Wextra -I.. plugin.c -o plugin.so ;;
esac
echo "built native example plugin"
