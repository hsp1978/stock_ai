#!/usr/bin/env python3
"""
Mac Studio 원격 설정 스크립트
SSH를 통해 Ollama 설치 및 설정
"""

import paramiko
import time
import sys
import getpass

def execute_command(ssh, cmd, description=""):
    """명령 실행 및 결과 출력"""
    if description:
        print(f"\n{description}")
    print(f"$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    output = stdout.read().decode()
    error = stderr.read().decode()
    if output:
        print(output)
    if error:
        print(f"Error: {error}")
    return output, error

def main():
    # SSH 연결
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print("=" * 70)
    print("Mac Studio Ollama 서버 설정")
    print("=" * 70)

    host = '100.108.11.20'
    username = 'hsptest'

    try:
        print("\n1. Mac Studio 접속 중...")
        # SSH 키 인증 우선, 실패 시 비밀번호 프롬프트
        try:
            ssh.connect(host, username=username, timeout=10)
        except paramiko.AuthenticationException:
            password = getpass.getpass(f"SSH 비밀번호 ({username}@{host}): ")
            ssh.connect(host, username=username, password=password, timeout=10)
        print("✅ 접속 성공!")

        # 2. Ollama 설치 확인
        print("\n2. Ollama 설치 확인...")
        output, _ = execute_command(ssh, "which ollama 2>/dev/null || echo 'not found'")

        if 'not found' in output:
            print("❌ Ollama 미설치 - 설치를 시작합니다...")

            # Ollama 설치
            print("\n3. Ollama 설치 중... (약 1-2분 소요)")
            install_cmd = "curl -fsSL https://ollama.ai/install.sh | sh"
            stdin, stdout, stderr = ssh.exec_command(install_cmd, get_pty=True)

            # 설치 진행 상황 표시
            while not stdout.channel.exit_status_ready():
                if stdout.channel.recv_ready():
                    output = stdout.channel.recv(1024).decode('utf-8')
                    print(output, end='')
                time.sleep(0.1)

            print("\n✅ Ollama 설치 완료!")
        else:
            print(f"✅ Ollama 이미 설치됨: {output.strip()}")

        # 3. Ollama 서비스 시작
        print("\n4. Ollama 서비스 설정...")

        # 환경 변수 설정 파일 생성
        env_setup = """
# Ollama 서버 설정
export OLLAMA_HOST="0.0.0.0:8080"
export OLLAMA_ORIGINS="*"
export OLLAMA_NUM_PARALLEL=2
export OLLAMA_MAX_LOADED_MODELS=2
"""
        execute_command(ssh, f'echo "{env_setup}" > ~/.ollama_env')

        # 서비스 시작 스크립트 생성
        start_script = """#!/bin/bash
source ~/.ollama_env
echo "Starting Ollama server on port 8080..."
ollama serve
"""
        execute_command(ssh, f'echo "{start_script}" > ~/start_ollama.sh')
        execute_command(ssh, "chmod +x ~/start_ollama.sh")

        # 4. 백그라운드에서 Ollama 시작
        print("\n5. Ollama 서버 시작...")
        execute_command(ssh, "pkill ollama 2>/dev/null || true")  # 기존 프로세스 종료
        time.sleep(1)

        # nohup으로 백그라운드 실행
        execute_command(ssh, "source ~/.ollama_env && nohup ollama serve > ~/ollama.log 2>&1 &")
        print("⏳ 서버 시작 중... (5초 대기)")
        time.sleep(5)

        # 5. 서버 상태 확인
        print("\n6. 서버 상태 확인...")
        output, _ = execute_command(ssh, "ps aux | grep ollama | grep -v grep")
        if output:
            print("✅ Ollama 서버 실행 중!")
        else:
            print("⚠️ 서버가 아직 시작되지 않았습니다.")

        # 6. 모델 다운로드
        print("\n7. 필요한 모델 다운로드...")

        # 현재 설치된 모델 확인
        output, _ = execute_command(ssh, "ollama list 2>/dev/null || echo 'no models'")
        print(f"현재 모델: {output}")

        # Qwen 32B 모델 다운로드 (Mac Studio용)
        models_to_install = [
            "qwen2.5:32b-instruct-q4_K_M",  # 메인 모델
            "qwen2.5:14b-instruct-q4_K_M",  # 폴백용
        ]

        for model in models_to_install:
            print(f"\n다운로드: {model}")
            output, error = execute_command(ssh, f"ollama pull {model}")
            if "success" in output.lower() or not error:
                print(f"✅ {model} 다운로드 완료")
            else:
                print(f"⚠️ {model} 다운로드 실패 또는 이미 존재")

        # 7. 최종 상태 확인
        print("\n8. 최종 설정 확인...")
        execute_command(ssh, "ollama list")

        # 네트워크 정보
        print("\n9. 네트워크 정보:")
        output, _ = execute_command(ssh, "ifconfig | grep 'inet ' | grep -v 127.0.0.1 | awk '{print $2}' | head -1")
        ip_address = output.strip()
        print(f"Mac Studio IP: {ip_address}")
        print(f"Ollama URL: http://{ip_address}:8080")

        print("\n" + "=" * 70)
        print("✅ Mac Studio 설정 완료!")
        print("=" * 70)
        print("\n다음 단계:")
        print("1. RTX 5070 서버의 dual_node.env 파일 수정:")
        print(f"   MAC_STUDIO_IP={ip_address}")
        print(f"   MAC_STUDIO_URL=http://{ip_address}:8080")
        print("\n2. 연결 테스트:")
        print("   python3 test_dual_node.py")

        ssh.close()

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()