# Phase 1 — Mac Studio Ollama Tailscale 노출 작업서

> 사용자가 **Mac Studio (`hsptest-macstudio`) 에서 직접** 실행할 명령. 이 머신(`testdev`) 에서는 검증만 수행.

## 사전 확인 (Mac Studio 에서)

```bash
# 1) Tailscale 활성 확인
tailscale status | head -3
# 자기 자신이 hsptest-macstudio (100.108.11.20) 으로 떠야 함

# 2) Ollama 설치 + 모델 확인
ollama --version
ollama list
# Qwen 32B 등 heavy 모델이 있어야 함
```

## 핵심 작업: Ollama를 Tailscale 인터페이스로 노출

Ollama 기본 바인드는 `127.0.0.1:11434` 라서 다른 노드에서 닿지 않음. 두 옵션 중 택1.

### 옵션 A — `OLLAMA_HOST` 환경변수 (권장)

```bash
# 임시 (현재 세션)
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"

# Ollama 재시작 (메뉴바 앱이면 Quit → 재실행, brew 설치면 아래)
brew services restart ollama 2>/dev/null || \
  (pkill -x ollama; nohup ollama serve >/tmp/ollama.log 2>&1 &)

# 영구화 — ~/.zshrc 또는 ~/.zprofile 에 추가
echo 'launchctl setenv OLLAMA_HOST "0.0.0.0:11434"' >> ~/.zprofile
```

> 참고: `0.0.0.0` 대신 `100.108.11.20` (Tailscale IP) 으로 좁히고 싶으면 그렇게 해도 동작. 다만 Tailscale 노드 재가입 시 IP가 바뀔 수 있으므로 보통은 `0.0.0.0` + 외부 ACL 로 제한하는 편이 안전.

### 옵션 B — Tailscale Serve (Ollama 재설정 없이 우회)

```bash
# Ollama는 그대로 두고, Tailscale 만으로 11434 를 tailnet 에 노출
sudo tailscale serve --bg --tcp=11434 tcp://localhost:11434

# 활성 상태 확인
tailscale serve status
```

옵션 A가 못 돌아갈 경우의 백업. 보안상으론 더 깔끔(외부 LAN 노출 안 됨).

## 검증 체크리스트

### Mac Studio 자체에서
```bash
curl -s http://localhost:11434/api/tags | head -20
# 모델 목록 응답하면 Ollama 자체는 OK
lsof -nP -iTCP:11434 -sTCP:LISTEN
# 옵션 A 적용됐다면 *:11434 (LISTEN) 에 ollama 가 보여야 함 (127.0.0.1: 가 아니라)
```

### testdev 머신에서 (내가 대신 수행 가능)
```bash
curl -sS --max-time 5 http://hsptest-macstudio:11434/api/tags
# JSON 모델 목록 리턴되면 Phase 1 핵심 성공
```

## Tailscale ACL (선택, 권장)

기본 ACL은 tailnet 안의 모든 노드가 모든 포트에 접근 가능. 좁히려면 admin console (https://login.tailscale.com/admin/acls) 에서:

```jsonc
{
  "acls": [
    // testdev → mac-studio 의 ssh + ollama 만 허용
    { "action": "accept", "src": ["testdev"], "dst": ["hsptest-macstudio:22,11434"] },
    // 나머지 노드는 mac-studio 못 건드리게 (예시 - 기존 정책 안 깨도록 추가만)
  ]
}
```

> 무료 플랜에서도 ACL 편집 가능. 다만 잘못 짜면 본인 SSH 도 끊길 수 있으니 **현재 ACL을 백업 후** 추가 형태로 적용 권장.

## 롤백

```bash
# 옵션 A
launchctl unsetenv OLLAMA_HOST
# ~/.zprofile 의 추가 라인 제거
brew services restart ollama
```
```bash
# 옵션 B
sudo tailscale serve --tcp=11434 off
```

## 완료 후 다음 단계

testdev 에서 `curl http://hsptest-macstudio:11434/api/tags` 가 정상이면 알려줘. 그 시점에 Task #5 (.env URL 교체) 진행:

- `dual_node.env.example` 의 `MAC_STUDIO_URL=http://192.168.1.100:8080` → `http://hsptest-macstudio:11434`
- 폴백 버그 (`stock_analyzer/dual_node_config.py:29`) 도 같이 수정
