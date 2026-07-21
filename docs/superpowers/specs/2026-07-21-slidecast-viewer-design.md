# Slidecast — HTML Slide Viewer 설계

- 날짜: 2026-07-21
- 상태: 설계 승인 대기 (유저 리뷰 게이트)
- 배포 대상: AWS 계정 `123456789012`, 자격증명 프로파일 `profile2`, 리전 `us-east-1`

## 1. 목적

`html-slide` 스킬로 만든 자기완결형(single self-contained `.html`) 슬라이드 덱을
한곳에 계속 누적(append)하고, 갤러리에서 선택해 풀스크린으로 재생(play)하는
개인용 웹 뷰어. 수정본 재업로드(update)와 삭제(delete)를 웹과 로컬 스킬
양쪽에서 지원한다.

핵심 통찰: html-slide 산출물은 서버 로직이 필요 없는 정적 HTML이다. 따라서
슬라이드 서빙은 S3 + CloudFront 정적 배포로 끝나고, 백엔드는 목록/업로드/삭제
메타데이터를 다루는 가벼운 서버리스 API만 있으면 된다. ALB/ECS는 불필요하며,
ALB 인터넷 노출로 인한 AWS 내부 스캐너(DyePack) 리스크도 원천 차단한다.

## 2. 범위

포함:
- 다크 시네마틱 React 뷰어 SPA (갤러리 + 풀스크린 재생 + 업로드 UI)
- 덱 라이프사이클: 누적(append) / 수정(update) / 삭제(delete)
- 버전 히스토리: 수정본마다 이전 버전을 보관하고 뷰어에서 선택·롤백
- 소프트 삭제(archived, 복원 가능) + 하드 삭제(영구 제거) 2단계
- 업로드 시 헤드리스(Chromium) 첫 화면 캡처로 버전별 썸네일 자동 생성
- Cognito 로그인(셀프 가입 차단, 관리자 사용자 1개)
- AWS CDK(Python) IaC
- 로컬 스킬 `slidecast-append`: profile2 자격증명으로 직접 S3+DDB 업로드/수정

제외 (YAGNI):
- 다중 사용자/팀 공유, 초대 플로우
- 플레이리스트(여러 덱 연속 재생)
- 덱 내부 슬라이드 단위 편집
- 버전 간 diff/비교 뷰 (버전 목록·재생·롤백까지만)

## 3. 아키텍처

```
개발자 로컬 ──(local skill: profile2 자격증명)──┐
                                              ▼ 직접 PUT + PutItem
사용자 브라우저                          S3(slides) + DynamoDB(meta)
   │                                          ▲
   ▼ HTTPS                                    │ (썸네일 캡처)
CloudFront (단일 배포, OAC)                Lambda(Chromium)
   ├─ /            → S3 (React 뷰어 SPA)       ▲
   ├─ /slides/*    → S3 (덱 .html, OAC 비공개)  │ S3 이벤트 트리거
   └─ /api/*       → API Gateway (HTTP API)
                       └─ Cognito JWT authorizer
                            └─ Lambda(API) ─→ DynamoDB / S3 presign
Cognito User Pool (셀프가입 차단, 관리자 사용자 1개) + Hosted UI
```

- ALB 없음. 인증은 CloudFront 앞단이 아니라 `/api`의 Cognito JWT authorizer +
  뷰어 SPA의 Hosted UI 로그인으로 처리한다.
- 모든 자원은 단일 CloudFront origin(same-origin) 아래에 있어 덱 iframe 로드 시
  CSP/CORS 충돌이 없다.

## 4. 스토리지 모델

### S3 버킷 1개 (프라이빗, CloudFront OAC로만 접근)
- `web/` — React 뷰어 빌드 산출물
- `slides/{deckId}/v{n}/index.html` — 버전별 self-contained 덱 (v1, v2, ...)
- `thumbnails/{deckId}/v{n}.png` — 버전별 헤드리스 캡처 결과

버전 파일은 불변(immutable)이라 `Cache-Control: public, max-age=31536000,
immutable`로 길게 캐시할 수 있다. 버전 키에 번호가 들어가므로 URL이 바뀌어
캐시 무효화가 필요 없다. 뷰어는 특정 버전 키를 직접 로드한다.

### DynamoDB 테이블 1개 (`SlideDecks`)
- PK: `deckId` (파일명 기반 슬러그, 예: `2026-roadmap`)
- 속성:
  - `title, tags[], createdAt, updatedAt`
  - `status` — `active` | `archived` (소프트 삭제 플래그)
  - `currentVersion` — 현재 재생/썸네일에 쓰는 버전 번호 (예: `2`)
  - `versions` — 버전 목록 배열:
    `[{ n, createdAt, thumbnailKey, sizeBytes, slideCount? }]`
- GSI `byUpdatedAt`: 갤러리 최신순 정렬 조회용 (파티션 키 `status`,
  정렬 키 `updatedAt`) → `active`만 최신순으로 조회, `archived` 별도 조회

`deckId`를 파일명 슬러그로 두면 같은 슬라이드의 수정본이 같은 항목으로
매핑된다. 수정본 업로드는 `currentVersion + 1` 번 버전을 새로 만들고
`versions`에 append한 뒤 `currentVersion`을 갱신한다(이전 버전은 그대로 보관).
충돌 시(웹) "새 버전으로 올릴지 / 다른 이름의 신규 덱으로 만들지" 묻는다.

## 5. 백엔드 (Lambda 2개)

### API Lambda (`/api`, Cognito authorizer 뒤)
- `GET /api/decks` — 활성 덱 목록(최신순, GSI 조회). `?status=archived`로
  보관함 조회
- `GET /api/decks/{id}` — 상세 + 버전 목록 + 현재/특정 버전 뷰 URL
- `POST /api/decks` — 신규 덱: `v1` 업로드용 presigned PUT URL 발급 + 메타 생성
- `PUT /api/decks/{id}` — 수정본: `currentVersion+1` 버전용 presigned PUT URL
  발급 (S3 PUT 완료 후 썸네일 Lambda가 `versions` append + `currentVersion` 갱신)
- `PUT /api/decks/{id}/current` — 롤백: `currentVersion`을 지정 버전으로 전환
- `DELETE /api/decks/{id}` — 소프트 삭제: `status=archived`로 전환 (파일·버전 보존)
- `POST /api/decks/{id}/restore` — 보관함에서 복원: `status=active`
- `DELETE /api/decks/{id}?hard=true` — 하드 삭제: `slides/{deckId}/`·
  `thumbnails/{deckId}/` 전체 프리픽스 + DDB 항목 영구 제거

### Thumbnail Lambda (S3 이벤트 트리거)
- `slides/{deckId}/v{n}/index.html` 생성 이벤트 → Chromium(Lambda layer)로 첫
  화면 1920×1080 렌더 → PNG → `thumbnails/{deckId}/v{n}.png` 저장
- DDB `versions`에 해당 버전 항목 append(idempotent), `currentVersion`·
  `updatedAt` 갱신. 신규(v1)와 수정본(v2+) 모두 이 경로를 탄다.

## 6. 뷰어 SPA (React + Vite, 다크 시네마틱)

- **갤러리**: 썸네일 카드 그리드(활성 덱 최신순), 검색/태그 필터, 부드러운
  hover/모션, 대형 타이포그래피. Apple/Linear 계열 고급 제품 페이지 느낌. 각
  카드에 수정/버전/삭제 액션(삭제는 확인 모달). 상단에 "보관함(archived)" 토글.
- **재생**: 카드 클릭 → 풀스크린 오버레이 iframe으로 현재 버전
  `slides/{deckId}/v{currentVersion}/index.html` 로드. 덱 자체의 html-slide 엔진
  키보드 네비게이션이 그대로 동작. ESC로 갤러리 복귀.
- **버전**: 상세/버전 드롭다운에서 버전 목록(썸네일·시각) 확인, 특정 버전 재생,
  "이 버전으로 롤백"(`PUT /current`) 버튼.
- **업로드**: 드래그앤드롭 → `POST /api/decks`(신규) 또는 `PUT`(수정, 새 버전) →
  presigned URL로 S3 직접 PUT → 썸네일 생성 대기 표시 → 갤러리 갱신.
- **삭제/복원**: 카드에서 소프트 삭제(보관함 이동), 보관함에서 복원 또는 영구 삭제.
- **인증**: Cognito Hosted UI 로그인 후 JWT를 `/api` 호출에 사용.

## 7. 로컬 스킬 (`slidecast-append`)

- 입력: html-slide로 만든 `.html` 경로 (+ 선택적 title/tags)
- 동작: profile2 자격증명으로
  1. deckId 슬러그 결정(파일명 기반). 기존 항목 존재 시 다음 버전으로 update,
     없으면 v1 신규(append).
  2. 대상 버전 번호 `n` 계산 후 S3 `slides/{deckId}/v{n}/index.html` PUT
  3. 로컬에서 첫 슬라이드 캡처(headless) 후 `thumbnails/{deckId}/v{n}.png` PUT
     (실패 시 S3 이벤트로 Lambda 캡처에 위임)
  4. DDB upsert: `versions`에 버전 append, `currentVersion`·`updatedAt` 갱신
- API 인증 우회(직접 SDK 호출), 개인 워크플로우에 최적.
- 추가 서브커맨드:
  - `slidecast-append --rollback {deckId} {n}` — 현재 버전 전환
  - `slidecast-append --delete {deckId}` — 소프트 삭제(보관함)
  - `slidecast-append --delete {deckId} --hard` — 영구 삭제

## 8. 보안

- S3 버킷은 완전 프라이빗, CloudFront OAC로만 접근. 퍼블릭 액세스 차단.
- Cognito User Pool: 셀프 가입(self sign-up) 비활성화, 관리자가 사용자 1개 생성.
- `/api`는 전부 Cognito JWT authorizer 뒤에 위치.
- ALB/퍼블릭 인바운드 없음 → DyePack/Epoxy 리스크 없음.
- presigned URL은 짧은 만료(예: 5분), PUT 대상 key/content-type 제한.
- IAM 최소 권한: Lambda는 해당 버킷/테이블에만, 로컬 스킬은 profile2 사용자 권한.

## 9. 리포지토리 구조 (예정)

```
/Workshop/html-viewer
├── infra/            # AWS CDK (Python) — S3, CloudFront, Cognito, API GW, Lambda, DDB
├── viewer/           # React + Vite SPA (다크 시네마틱)
├── lambdas/
│   ├── api/          # 목록/업로드/수정/삭제 핸들러
│   └── thumbnail/    # Chromium 헤드리스 캡처
├── skill/            # slidecast-append 로컬 스킬
└── docs/superpowers/specs/
```

## 10. 성공 기준

- 웹에서 로그인 후 `.html` 덱을 업로드하면 갤러리에 썸네일과 함께 나타난다.
- 갤러리에서 덱을 클릭하면 풀스크린으로 재생되고 키보드 네비게이션이 동작한다.
- 같은 덱의 수정본을 올리면 새 버전이 추가되고, 이전 버전은 보관되며 썸네일도
  버전별로 생성된다. 버전 목록에서 이전 버전을 재생/롤백할 수 있다.
- 소프트 삭제한 덱은 갤러리에서 사라지고 보관함에서 복원 가능하며, 하드 삭제하면
  S3·DDB에서 모든 버전이 영구 제거된다.
- 로컬 스킬 한 번 실행으로 방금 만든 덱이 갤러리에 append/update(새 버전) 된다.
- 퍼블릭 인바운드/ALB 노출이 없고 S3는 OAC 경유로만 접근된다.
