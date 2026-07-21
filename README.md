# Slidecast

html-slide로 만든 self-contained HTML 슬라이드 덱을 누적/수정(버전)/삭제하고,
갤러리에서 선택해 풀스크린으로 재생하는 개인용 서버리스 웹 뷰어.

- 배포: AWS 계정 `123456789012`, 리전 `us-east-1`, 자격증명 프로파일 `profile2`
- 라이브 URL: https://d2o39fnd1gcpgv.cloudfront.net

## 아키텍처

```
개발자 로컬 ──(local skill: profile2 자격증명)──┐
                                              ▼ 직접 PUT + PutItem
사용자 브라우저                          S3(slides) + DynamoDB(SlideDecks)
   │                                          ▲
   ▼ HTTPS                                    │ (썸네일 캡처)
CloudFront (단일 배포, OAC)          Thumbnail Lambda (container image, Chromium)
   ├─ /            → S3 (React 뷰어 SPA)       ▲
   ├─ /slides/*    → S3 (덱 .html, OAC 비공개)  │ S3 이벤트 트리거
   ├─ /thumbnails/*→ S3 (썸네일 PNG)            │
   └─ /api/*       → API Gateway (HTTP API)
                       └─ Cognito JWT authorizer
                            └─ API Lambda ─→ DynamoDB / S3 presign
Cognito User Pool (셀프가입 차단, 관리자 사용자 1개) + Hosted UI
```

- ALB/퍼블릭 인바운드 없음. S3는 완전 프라이빗, CloudFront OAC로만 접근.
- `/api`는 전부 Cognito JWT authorizer 뒤. 뷰어는 id_token을 Bearer로 전송.
- 덱은 버전 관리: `slides/{deckId}/v{n}/index.html`, `thumbnails/{deckId}/v{n}.png`.
- 버전 번호는 단조 증가(`max(n)+1`) — 롤백 후 재업로드해도 이전 버전을 덮어쓰지 않음.
- 버전 레코드는 API가 업로드 시점에 생성(권위), 썸네일 Lambda는 thumbnailKey만 채움.

## 구성 요소

| 경로 | 역할 |
|------|------|
| `infra/` | AWS CDK (Python) 스택 — S3, CloudFront, Cognito, API GW, Lambda, DDB |
| `lambdas/api/` | HTTP API 핸들러 (목록/업로드/버전/롤백/소프트·하드 삭제/복원) |
| `lambdas/thumbnail/` | S3 이벤트 → Chromium 헤드리스 첫 화면 캡처 (컨테이너 이미지 Lambda) |
| `shared/deck_model.py` | 불변 덱/버전 데이터 모델 (API·썸네일·스킬 공용) |
| `viewer/` | React + Vite + TS SPA (다크 시네마틱) |
| `skill/slidecast-append/` | 로컬 스킬 — profile2로 직접 S3+DDB 업로드/버전/삭제 |

## 데이터 모델 (DynamoDB `SlideDecks`)

- PK `deckId` (파일명 슬러그), GSI `byUpdatedAt` (PK `status`, SK `updatedAt`)
- 속성: `title, tags[], status(active|archived), currentVersion, versions[], createdAt, updatedAt`
- `versions[]` 항목: `{n, createdAt, thumbnailKey, sizeBytes, slideCount}`

## 배포 순서

전제: 배포 호스트에 Docker 필요(썸네일 Lambda가 컨테이너 이미지). profile2 CDK bootstrap 완료.

```bash
# 1) 인프라 배포 (S3, CloudFront, Cognito, API, Lambda, DDB)
#    shared layer + thumbnail 빌드 자산을 복사한 뒤 cdk deploy
./scripts/deploy.sh

# 2) Cognito 로그인 사용자 생성 (셀프 가입 비활성 — 관리자가 수동 생성)
./scripts/create-user.sh you@example.com

# 3) 뷰어 빌드 + S3 배포 + CloudFront 무효화 + Cognito 콜백 URL 설정
./scripts/deploy-viewer.sh
```

`scripts/deploy-viewer.sh`는 CloudFront 도메인을 알아야 하는 Cognito callback/logout
URL을 배포 후 자동으로 설정한다(합성 시엔 localhost placeholder).

## 로컬 스킬 사용 (slidecast-append)

html-slide로 만든 덱을 갤러리에 바로 반영한다.

```bash
export AWS_PROFILE=profile2 AWS_REGION=us-east-1
export BUCKET_NAME=<cdk-outputs의 BucketName>
python3 -m playwright install chromium   # 최초 1회 (로컬 썸네일 캡처용)

# 신규/수정 업로드 (파일명 슬러그가 기존 덱과 같으면 새 버전으로 추가)
python3 skill/slidecast-append/slidecast_append.py deck.html --title "제목" --tags biz,2026

# 롤백 / 소프트 삭제 / 영구 삭제
python3 skill/slidecast-append/slidecast_append.py --rollback <deckId> <n>
python3 skill/slidecast-append/slidecast_append.py --delete <deckId>
python3 skill/slidecast-append/slidecast_append.py --delete <deckId> --hard
```

## 테스트

```bash
python3 -m pytest tests/ -q        # 백엔드/인프라/스킬 (moto 목킹)
cd viewer && npx vitest run        # 뷰어 유닛 테스트
cd viewer && npx tsc --noEmit      # 타입체크
```

## 보안 노트 (개인용 도구 기준)

- S3 `BLOCK_ALL` + OAC + TLS 강제, Cognito self sign-up 비활성, 모든 `/api` JWT 보호.
- 슬라이드는 CloudFront에서 URL로 접근 가능(개인 명시적 URL 전제). 업로드 HTML은
  `sandbox="allow-scripts"`(same-origin 제외) iframe에서 실행 — 부모 오리진/토큰 접근 차단.
- 인증 토큰은 sessionStorage(탭 세션 한정) 보관.
- 팀 공유·공개 서비스로 확장 시: `/slides/*` signed URL/cookie, 슬라이드 별도 오리진 격리 재검토.
