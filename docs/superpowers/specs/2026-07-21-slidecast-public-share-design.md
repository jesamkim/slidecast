# Slidecast v3 — Public 공유 + 다운로드 설계

- 날짜: 2026-07-21
- 상태: 설계 승인 대기 (유저 리뷰 게이트)
- 기반: 배포된 Slidecast v2 (https://d2o39fnd1gcpgv.cloudfront.net,
  계정 123456789012 / us-east-1 / profile2)
- 선행 스펙: `2026-07-21-slidecast-viewer-design.md`,
  `2026-07-21-slidecast-groups-alias-design.md`

## 1. 목적

업로드된 덱마다 "공유" 토글을 제공한다. 공개(ON)하면 추측 불가 토큰이 발급되고
`https://<도메인>/p/{token}`을 **로그인 없이** 열면 그 덱의 공개 스냅샷이 풀스크린
재생된다. 링크·복사 버튼·재발행·공개 배지는 카드의 "공유" 버튼이 여는 **공유
모달**에 표시된다. OFF하면 공개 복사본·토큰·리졸브가 즉시 삭제돼 링크가 무효화된다.

## 2. 범위

포함:
- 덱별 공개 토글(공유 모달 UI: 링크 표시 + 복사 + 재발행 + OFF + 공개 배지)
- 무인증 공개 재생 페이지 `/p/{token}`
- 무인증 공개 메타 API `GET /api/public/{token}` (그 라우트만 열림)
- 공개 시 현재 버전 HTML을 `public/{token}/index.html`로 복사(공개 스냅샷)
- 토큰 원자 예약(조건부 쓰기), OFF/재공개 시 새 토큰 발급
- 수정본 반영은 명시적 "재발행"(자동 아님)
- 로컬 스킬 `--share`/`--unshare`
- hard delete 시 공개 복사본·토큰 정리
- **다운로드**: 로그인 사용자가 덱을 원본 `.html` 또는 PDF로 다운로드. PDF는
  업로드 시 사전 생성(썸네일과 같은 S3 이벤트 경로).

제외 (YAGNI):
- 사람이 읽는 공개 slug (추측 불가 토큰만)
- 공개 공유 페이지에서의 다운로드(다운로드는 로그인 사용자 전용; 공개 페이지는 보기 전용)
- 워터마크/조회수 통계
- 공개 링크 만료 시간(수동 OFF만)
- 공개 상태에서 수정본 자동 최신 반영(명시적 재발행만)
- 비밀번호 보호 공유
- 온디맨드 PDF 변환(업로드 시 사전 생성으로 대체)

## 3. 데이터 모델 (DynamoDB `SlideDecks`)

### 덱 아이템 (필드 추가)
- `publicToken`: string | null — 공개 중이면 토큰, 아니면 없음(sparse; put이 None
  키 제거하므로 미공개 덱엔 키 부재).
- `versions[]` 항목에 `pdfKey: string | null` 추가 — 해당 버전의 사전 생성 PDF S3
  키. PDF 생성 전/실패 시 없음(다운로드 UI는 PDF 미준비 시 비활성/대기 표시).

### 공개 리졸브 아이템 (신규, alias 예약과 동일 패턴)
- PK `deckId` = `PUBLIC#{token}`
- `type: "public"`, `ownerDeckId`, `publicVersion`(공개 시점 버전 번호), `createdAt`
- byUpdatedAt/byAlias GSI에 나타나지 않도록 `status`/`updatedAt`/`alias` 속성 미설정.
  토큰 조회는 PK 직접 조회(`get(public_pk(token))`).

## 4. S3 레이아웃

- `public/{token}/index.html` — 공개 시점 현재 버전 HTML의 복사본. deckId·버전
  구조 미노출. 공개 페이지가 same-origin으로 이 경로를 iframe 로드.
- OFF 시 `public/{token}/` 프리픽스 삭제.
- `pdfs/{deckId}/v{n}.pdf` — 업로드 시 사전 생성한 버전별 PDF. 프라이빗(CloudFront
  OAC), 다운로드는 API presigned URL 경유(직접 URL 노출 안 함).

## 5. CloudFront / 인증 경계 (핵심)

- 무인증으로 여는 것은 **정확히 두 가지**뿐:
  1. API 라우트 `GET /api/public/{token}` — 이 라우트만 `HttpNoneAuthorizer()`로
     명시 오픈. 나머지 `/api/*`는 전부 기존 JWT authorizer 유지.
  2. S3 `public/*` 프리픽스 — CloudFront 기본 동작으로 서빙(이미 URL 접근 가능).
- `/p/{token}`은 기존 SPA 폴백(403/404→index.html)으로 처리 → 공개 페이지
  컴포넌트가 클라이언트에서 렌더.
- 보안 격리: `slides/`·`thumbnails/`·나머지 `/api`는 그대로 로그인/JWT 뒤. 공개
  페이지는 `GET /api/public/{token}`만 호출하며 다른 API·경로에 접근하지 않는다.

## 6. API (기존 API Lambda에 추가)

- `PUT /api/decks/{id}/share` (JWT) — 공개 ON:
  - 이미 공개면 기존 토큰 반환(멱등).
  - 아니면 추측 불가 토큰 생성 → `public/{token}/index.html`에 현재 버전 복사 →
    `PUBLIC#{token}` 조건부 예약(`attribute_not_exists`) → 덱 `publicToken` 설정.
  - 반환: `{token, url: "/p/{token}"}`
- `POST /api/decks/{id}/share/republish` (JWT) — 공개 상태에서 현재 버전 HTML을
  `public/{token}/index.html`에 다시 복사, `publicVersion` 갱신. 미공개면 400.
- `DELETE /api/decks/{id}/share` (JWT) — 공개 OFF: `public/{token}/` 삭제 +
  `PUBLIC#{token}` 삭제 + 덱 `publicToken=null`.
- `GET /api/public/{token}` (**무인증**) — 공개 덱 최소 메타 반환:
  `{title, htmlUrl: "/public/{token}/index.html"}`. 비공개/없는 토큰 404.
  deckId·버전·태그·그룹 등 내부 정보 미노출.
- `GET /api/decks/{id}/download?format=html|pdf&version={n}` (JWT) — 다운로드 URL
  발급. `version` 생략 시 현재 버전. `html`이면 `slides/{deckId}/v{n}/index.html`,
  `pdf`면 `pdfs/{deckId}/v{n}.pdf`에 대한 **presigned GET URL**(짧은 만료, 예 300s,
  `Content-Disposition: attachment; filename="{title}-v{n}.{ext}"`) 반환
  `{downloadUrl}`. PDF가 아직 없으면(생성 전/실패) 409 "pdf not ready".

토큰: `secrets.token_urlsafe`류 추측 불가 문자열(URL-safe). 예약은 조건부 쓰기라
충돌 시 재생성.

## 6-1. 다운로드 (로그인 사용자 전용)

- 대상: 갤러리에서 로그인한 사용자만. 공개 공유 페이지에는 다운로드 없음(보기 전용).
- 형식:
  - **원본 .html** — 업로드된 self-contained 파일 그대로. 오프라인 재생 가능,
    브라우저에서 Ctrl+P로 PDF 저장도 가능.
  - **PDF** — 업로드 시 사전 생성(§ 썸네일/PDF Lambda). 다운로드 즉시.
- 서빙: 파일은 프라이빗 S3. `GET /api/decks/{id}/download`가 presigned GET URL을
  발급하고 브라우저가 그 URL로 받는다(`attachment` 헤더로 저장 유도).
- UI: 카드/버전 메뉴에 "다운로드" — HTML / PDF 선택. PDF 미준비면 해당 옵션 비활성
  + "PDF 생성 중" 안내(썸네일과 동일한 지연 특성).

## 7. 뷰어

- **공개 페이지** `/p/{token}` (App 라우트):
  - 로그인 게이트 없이 즉시 `GET /api/public/{token}` 호출.
  - 성공 → 풀스크린 iframe으로 `htmlUrl` 로드(sandbox `allow-scripts`, same-origin
    제외 — 기존 Player와 동일). 최소 크롬(제목 정도), 갤러리·다른 덱 접근 없음.
  - 404 → "만료되었거나 존재하지 않는 링크" 안내.
- **공유 모달** (카드/상세의 "공유" 버튼):
  - 공개 토글(ON/OFF). ON 시 `PUT .../share` → 링크 표시 + 복사 버튼 + "재발행"
    버튼 + 공개 배지. OFF 시 `DELETE .../share`(확인).
  - 재발행: `POST .../share/republish`.
  - double-submit 가드(alias/group 수정에서 쓴 재진입 가드 재사용).
- 카드: 공개 중이면 작은 배지 표시. 공유 모달이 링크/컨트롤을 담당(카드는 간결 유지).
- **다운로드 UI**: 카드/버전 메뉴에 다운로드(HTML/PDF). `GET .../download`로 받은
  presigned URL로 브라우저가 저장. PDF 미준비(409)면 옵션 비활성 + "PDF 생성 중".

## 7-1. PDF 사전 생성 (썸네일 Lambda 확장)

- 기존 Thumbnail Lambda(컨테이너 이미지, Chromium)가 S3 `slides/{deckId}/v{n}/
  index.html` 생성 이벤트에서 썸네일 PNG와 함께 **PDF도 생성**한다.
- Chromium print-to-PDF(html-slide 엔진의 print CSS 활용)로 `pdfs/{deckId}/v{n}.pdf`
  저장 후 DDB 해당 버전의 `pdfKey` 갱신(불변 헬퍼, 썸네일과 동일 idempotent 경로).
- 로컬 스킬의 로컬 캡처 경로도 선택적으로 PDF 생성 가능(실패 시 Lambda 이벤트에
  위임). 최소 요건은 Lambda 경로에서 PDF가 생성되는 것.

## 8. 로컬 스킬 (`slidecast-append`)

- `--share <deckId>` — 공개 ON, 발급된 `/p/{token}` 출력.
- `--unshare <deckId>` — 공개 OFF(복사본·토큰 정리).
- hard delete가 덱의 `publicToken`이 있으면 공개 복사본·토큰도 정리.
- hard delete 시 `pdfs/{deckId}/` 프리픽스도 함께 정리.

## 9. 하드닝 (이전 리뷰 교훈)

- 토큰 예약은 alias와 동일한 조건부 쓰기 원자 예약(경쟁 제거, GSI 오염 없음).
- OFF 후 재공개 시 새 토큰 → 유출된 옛 링크 무효 유지.
- 공유 모달 제출 버튼 double-submit 가드.
- 무인증 API 라우트는 `GET /api/public/{token}` 하나로 최소화(쓰기·다른 조회는
  전부 JWT). 무인증 S3 노출은 `public/*` 프리픽스로 한정.
- 공개 iframe sandbox 유지(공개받은 브라우저에서 실행되나 우리 오리진 접근 차단).

## 10. 검증 · 엣지 케이스

- 무인증 라우트가 공개 덱만 반환하고 비공개/오토큰은 404(내부정보 미노출).
- OFF 후 옛 토큰으로 접근 시 404(리졸브·복사본 모두 삭제됨).
- 재공개가 새 토큰을 발급(옛 링크 재활성 안 됨).
- 재발행 없이 덱 수정 시 공개 스냅샷은 옛 버전 유지(자동 반영 안 됨).
- hard delete가 공개 복사본·토큰까지 정리(고아 방지).
- CloudFront 무인증 노출은 `/api/public/*`와 `public/*`로 한정(나머지 보호 유지).

## 11. 성공 기준

- 덱 카드의 "공유"로 공개하면 모달에 `/p/{token}` 링크와 복사 버튼이 뜬다.
- 로그아웃/시크릿 창에서 그 링크를 열면 로그인 없이 덱이 풀스크린 재생된다.
- 공유 OFF하면 같은 링크가 즉시 404가 된다.
- 재공개하면 새 토큰이 나오고 옛 링크는 여전히 무효다.
- 공개 중 수정 후 "재발행"하면 공개본이 최신 버전으로 갱신된다.
- 공개 페이지에서 갤러리·다른 덱·비공개 API에 접근할 수 없다.
- 로컬 스킬 `--share`/`--unshare`가 동작한다.
- 로그인 사용자가 카드/버전 메뉴에서 덱을 원본 .html 또는 PDF로 다운로드할 수 있다.
- PDF는 업로드 후 자동 생성되어(썸네일과 같은 경로) 준비되면 다운로드 가능하고,
  준비 전에는 옵션이 비활성으로 표시된다.
- 다운로드 파일은 프라이빗 S3에서 presigned URL로만 제공되며 직접 URL은 노출되지 않는다.
- 공개 공유 페이지에는 다운로드 기능이 없다(보기 전용).
