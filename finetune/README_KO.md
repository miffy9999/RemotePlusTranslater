# 호텔 번역 LoRA 준비

## 현재 상태

- 운영 모델: `tencent/Hy-MT2-1.8B` 기반 Q4_K_M GGUF
- 라이선스: Apache-2.0
- 데이터: 영어·한국어를 최우선으로 한 학습 seed 40건, 학습 미사용 holdout 8건
- 운영 PC: NVIDIA GPU가 없으므로 추론 전용
- Sakura VPS 2GB: 다운로드·업데이트 제공용이며 모델 학습이나 추론용이 아님

공식 Hy-MT2 문서상 1.8B LoRA도 최대 길이 8192 설정에서는 24GB 이상 GPU 한 장이
필요합니다. 따라서 2GB VPS에서 학습을 시도하거나 운영 번역을 VPS로 옮기지 않습니다.

## 데이터 만들기

Windows 개발 PC에서 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe scripts\prepare_finetune_data.py
```

이 명령은 schema, 중복 ID, train/holdout 누출, 언어별 균형, 카드번호·전화번호·이메일 모양을
검사한 뒤 다음 파일을 만듭니다.

- `cache/finetune/hotel_train.jsonl`
- `cache/finetune/hotel_holdout.jsonl`

각 행은 공식 Hy-MT2가 요구하는 `messages` 형식입니다. 실제 통화에서 모은 교정문은 고객·직원
동의, 완전 익명화, 사람 번역 검수를 거친 뒤에만 seed에 추가합니다. 모델 출력물을 그대로 정답
데이터로 되먹이지 않습니다.

## GPU 환경에서 학습

학습 시점에는 Hy-MT2 모델 카드의 `train/README.md`를 기준으로 공식 코드를 고정된 commit으로
clone합니다. 공식 가이드가 바뀔 수 있으므로 저장소에 오래된 설치 명령을 복제하지 않습니다.

권장 시작값은 LoRA, q/k/v/o projection, rank 16, alpha 32, dropout 0.05, 최대 길이 1024 이하,
작은 학습률입니다. 이것은 확정된 배포 설정이 아니라 첫 후보를 만들기 위한 값입니다. epoch와
학습률은 train loss가 아니라 미사용 holdout의 사람 평가로 선택합니다.

학습 결과는 BF16 원본 모델에 병합한 뒤, 현재 앱에 고정된 llama.cpp 버전으로 Q4_K_M GGUF를
만듭니다. 다른 quant나 runtime으로 동시에 바꾸면 모델 변화와 runtime 변화의 효과를 구분할 수
없으므로 한 번에 한 요소만 변경합니다.

## 승격 게이트

기본 모델을 먼저 3회 측정합니다.

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_hymt2.py `
  --repeats 3 `
  --report cache\baseline-q4.json
```

동일 PC가 유휴 상태일 때 후보를 3회 측정합니다.

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_hymt2.py `
  --model C:\candidate\hotel-hymt2-q4_k_m.gguf `
  --repeats 3 `
  --report cache\candidate-q4.json `
  --baseline-report cache\baseline-q4.json
```

종료 코드가 0이어야 하며 다음을 모두 만족해야 합니다.

- 고정 corpus 실패 0건
- 영어·한국어 중심 forward/reverse 점수 하락 없음
- neural model 경로 중앙 지연 하락 또는 동일
- neural model 경로 p95 지연 하락 또는 동일
- holdout 8건을 직원이 직접 비교해 부정, 숫자, 정책, 약속, 존댓말 후퇴 없음
- 실제 권리 확보 WAV에서 STT 결과가 같을 때 번역 품질 후퇴 없음

하나라도 실패하면 운영 모델 경로를 바꾸지 않습니다. Q4_K_M과 다른 양자화 모델은 작고 빠를 수
있지만 품질이 같다는 뜻은 아니므로 같은 게이트를 반드시 거칩니다.

## 공식 자료

- 모델 및 라이선스: https://huggingface.co/tencent/Hy-MT2-1.8B
- 공식 학습 가이드: https://huggingface.co/tencent/Hy-MT2-1.8B/blob/main/train/README.md
- 공식 GGUF: https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF
