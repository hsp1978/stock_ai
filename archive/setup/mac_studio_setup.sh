#!/bin/bash
# Mac Studio Ollama 서버 설정 스크립트
# Mac Studio에서 실행

echo "========================================"
echo "Mac Studio Ollama Server Setup"
echo "========================================"

# 1. Ollama 설치 확인
if ! command -v ollama &> /dev/null; then
    echo "Installing Ollama..."
    curl -fsSL https://ollama.ai/install.sh | sh
fi

# 2. 필요한 모델 다운로드
echo ""
echo "Downloading required models..."
echo "--------------------------------"

# Qwen3-30B-A3B-MLX-4bit (Mac 최적화)
# 참고: 실제 모델 이름은 변경될 수 있음
ollama pull qwen3:30b-q4_K_M 2>/dev/null || echo "⚠️ Qwen3-30B not available yet"

# EXAONE-4.0-32B (한국어 특화)
ollama pull exaone:32b 2>/dev/null || echo "⚠️ EXAONE-32B not available yet"

# 폴백용 모델 (확실히 존재하는 모델)
ollama pull qwen2.5:32b-instruct-q4_K_M || echo "Installing Qwen 2.5 32B..."

# 3. 서버 설정
echo ""
echo "Configuring Ollama server..."
echo "--------------------------------"

# 환경 변수 설정
export OLLAMA_HOST="0.0.0.0:8080"  # 외부 접근 허용
export OLLAMA_ORIGINS="*"          # CORS 허용
export OLLAMA_NUM_PARALLEL=2       # Mac Studio는 메모리가 많으므로 2개 동시 가능
export OLLAMA_MAX_LOADED_MODELS=2  # 최대 2개 모델 로드

# 4. 서버 실행 스크립트 생성
cat > ~/start_ollama_server.sh << 'EOF'
#!/bin/bash
# Ollama 서버 실행 스크립트

export OLLAMA_HOST="0.0.0.0:8080"
export OLLAMA_ORIGINS="*"
export OLLAMA_NUM_PARALLEL=2
export OLLAMA_MAX_LOADED_MODELS=2

echo "Starting Ollama server on Mac Studio..."
echo "URL: http://$(hostname):8080"
echo "Press Ctrl+C to stop"

# 서버 시작
ollama serve
EOF

chmod +x ~/start_ollama_server.sh

# 5. LaunchAgent 생성 (자동 시작)
cat > ~/Library/LaunchAgents/com.ollama.server.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ollama.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/ollama</string>
        <string>serve</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_HOST</key>
        <string>0.0.0.0:8080</string>
        <key>OLLAMA_ORIGINS</key>
        <string>*</string>
        <key>OLLAMA_NUM_PARALLEL</key>
        <string>2</string>
        <key>OLLAMA_MAX_LOADED_MODELS</key>
        <string>2</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/ollama.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ollama.error.log</string>
</dict>
</plist>
EOF

# 6. 서비스 로드
launchctl unload ~/Library/LaunchAgents/com.ollama.server.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.ollama.server.plist

# 7. 테스트
echo ""
echo "Testing Ollama server..."
echo "--------------------------------"

sleep 3
if curl -s http://localhost:8080/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama server is running!"
    echo ""
    echo "Available models:"
    curl -s http://localhost:8080/api/tags | python3 -c "
import json, sys
data = json.load(sys.stdin)
for model in data.get('models', []):
    print(f\"  - {model['name']}: {model['size']/(1024**3):.1f} GB\")
"
else
    echo "❌ Server not responding. Please run manually:"
    echo "   ~/start_ollama_server.sh"
fi

echo ""
echo "========================================"
echo "Setup complete!"
echo ""
echo "Server URL: http://$(hostname):8080"
echo "To test from another machine:"
echo "  curl http://$(hostname):8080/api/tags"
echo ""
echo "To start manually:"
echo "  ~/start_ollama_server.sh"
echo "========================================"