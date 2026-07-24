# 2026-07 구조·모델 최종 검토

검토일: 2026-07-16

## 결론

앞으로도 절대로 더 나은 구조가 불가능하다고 증명할 수는 없다. 새 모델, 공식 CPU runtime,
현장 하드웨어가 계속 바뀌기 때문이다. 다만 Intel CPU Windows PC, 영어·한국어 우선 일본어
상담, 로컬 개인정보 처리, 속도 저하 금지, 무료 상업 이용, Sakura VPS 2GB와 별도 채팅
프로그램 공존을 동시에 만족하는 현재 최선은 다음 구조다.

```text
마이크/WAV → 로컬 VAD → 로컬 Whisper small → 즉시 문구/번역 메모리
                                          → Hy-MT2 1.8B Q4 1회 호출
                                          → 채팅 카드/읽기 보조

Sakura VPS 2GB → 정적 다운로드 사이트 + 서명된 업데이트 파일만 제공
```

VPS에 STT·번역을 올리거나 더 큰 모델로 교체하는 것은 현재 조건에서는 개선이 아니다.

## 번역 모델 비교

| 후보 | 라이선스/비용 | 판단 |
|---|---|---|
| Hy-MT2 1.8B Q4_K_M | Apache-2.0, 실행료 없음 | 채택. 기존 128건 회귀 1.000/1.000, CPU 실행 가능 |
| Hy-MT2 1.8B 1.25-bit | Apache-2.0, 440MB | 직접 시험했으나 고정 runtime이 tensor type 42를 지원하지 않아 로드 실패 |
| Hy-MT2 7B Q4_K_M | Apache-2.0, GGUF 4.62GB | 약 4배 큰 weight로 CPU 지연·메모리가 증가하므로 속도 조건 위반 |
| TranslateGemma 4B | Gemma Terms, 4B | 더 크고 별도 사용조건 동의가 필요해 단순한 자유 라이선스 조건에 덜 적합 |
| MiLMMT-46 4B/12B | Gemma Terms | 연구 품질은 유망하지만 더 크고 느리며 Apache-2.0이 아님 |
| Qwen-MT | 유료 cloud API | 오프라인 무료가 아니며 음성·대화를 외부로 보내므로 제외 |
| NLLB/Seamless 계열 | 비상업 제한 모델 | 상업 사용 조건과 충돌하므로 제외 |
| 개인 공개 Gemma3 270M 번역 모델 | 카드에는 Apache, 기반은 Gemma Terms | 기반 라이선스와 표기가 불일치하고 독립 품질 근거가 부족해 제외 |

Hy-MT2는 2026년 5월 공개된 최신 번역 전용 계열이며 한국어·영어·일본어를 포함한다. 1.8B는
현재 PC에서 가능한 크기와 품질의 Pareto 지점이다. 큰 모델의 절대 품질이 더 높을 수는 있지만
“속도 저하 없음”을 동시에 만족하지 않는다.

## STT 모델 비교

| 후보 | 라이선스/강점 | 판단 |
|---|---|---|
| Whisper small + faster-whisper | Apache-2.0/MIT, 검증된 CPU INT8 | 현재 채택. portable Windows와 timestamp/VAD가 안정적 |
| Qwen3-ASR 0.6B | Apache-2.0, 52개 언어, 2026 공개 | 가장 유망한 차기 후보. 공식 고속/streaming 경로가 CUDA vLLM 중심이고 CPU 속도 미검증 |
| Qwen3-ASR 1.7B | Apache-2.0, 공개 평가 품질 우수 | 더 큰 decoder와 GPU 중심 runtime 때문에 현 PC에서는 제외 |
| SenseVoice Small | 상업 사용 허용 custom 라이선스, 5개 핵심 언어 | 언어 범위 축소와 별도 귀속 조건, 현장 corpus 부재로 즉시 교체하지 않음 |
| 언어별 Moonshine | 작은 언어별 모델 | 여러 모델 상주로 자동 언어/WAV 혼합 처리와 메모리 관리가 복잡해짐 |

Qwen3-ASR는 권리가 확보된 호텔 음성에서 다음을 모두 통과할 때만 별도 branch에서 교체한다.

1. 영어·한국어·일본어의 조용한 음성, 로비 소음, 전화 코덱, 작은 목소리 평가셋을 분리한다.
2. Whisper small과 WER/CER, 숫자·예약명·부정문 정확도를 비교한다.
3. cold load, warm p50/p95, peak RAM, 30분 연속 실행, EXE 전체 크기를 측정한다.
4. 현장 CPU에서 정확도가 높고 p50/p95가 모두 느려지지 않을 때만 채택한다.
5. community ONNX가 아니라 공식 weight와 재현 가능한 변환·해시를 사용한다.

공개 benchmark는 선별 근거일 뿐 호텔 전화 품질의 승격 근거가 아니다.

## 현재 파이프라인이 적합한 이유

- STT와 번역을 분리해야 원문 확인, 직원/고객 카드, 교정, WAV timestamp, 오류 원인 분리가
  가능하고 한 단계가 실패해도 원문을 남길 수 있다.
- `こんばんは`, 부정문, 상담 고정 문구, `그건 빼 주세요` 같은 고위험·고빈도 문장은 즉시
  번역 메모리가 처리하고 나머지는 Hy-MT2가 처리한다. 이는 순수 대형 모델보다 빠르고 순수
  규칙보다 범용적이다.
- 라이브는 미래 문장을 기다리지 않고 확정된 앞 문장만 사용한다. WAV는 STT 완료 후 앞·뒤
  문장을 모두 쓰되 두 경우 모두 현재 문장당 번역 호출은 한 번이다.
- 2GB VPS에서 Whisper, Hy-MT2, 채팅, DB를 함께 돌리면 RAM 부족, swap, OOM과 단일 장애점이
  생긴다. 로컬 추론은 외부 전송과 인터넷 왕복을 없애고 VPS의 정적 Caddy만 공존시킨다.

## 가능한 미래 개선

- 호텔에 NVIDIA GPU 서버가 생기면 중앙 Qwen3-ASR/Hy-MT2 7B A/B 시험은 가능하다. 네트워크
  장애 fallback과 음성 개인정보 계약이 전제다.
- 공식 1.25-bit Windows CPU runtime이 안정화되면 격리된 runtime으로 다시 시험한다.
- 스테레오 채널이나 고객/직원 마이크가 분리되면 AI diarization보다 채널 정보를 우선한다.
- 실제 교정문이 방향별 100건 이상 쌓이면 준비된 LoRA 파이프라인으로 후보를 학습한다.
- 품질과 속도 gate를 모두 통과하지 않으면 어떤 최신 모델도 운영본에 넣지 않는다.

## 무료 상업 이용의 의미

현재 로컬 모델은 호출료나 로열티가 없고 Apache/MIT/BSD/ISC 고지를 배포한다. 그러나 서버비
외 비용이 절대로 없다고 보장할 수는 없다. 호텔 IT가 자체 서명 인증서를 신뢰하면 공개 코드서명
인증서 비용을 피할 수 있지만 도메인, 백업, 법률 검토, 공인 코드서명이 필요하면 별도 비용이다.

## 공식 확인 자료

- https://huggingface.co/tencent/Hy-MT2-1.8B
- https://arxiv.org/abs/2605.22064
- https://huggingface.co/tencent/Hy-MT2-7B-GGUF
- https://github.com/QwenLM/Qwen3-ASR
- https://huggingface.co/Qwen/Qwen3-ASR-0.6B-hf
- https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/
- https://ai.google.dev/gemma/terms
- https://huggingface.co/collections/xiaomi-research/milmmt-46
- https://github.com/FunAudioLLM/SenseVoice
