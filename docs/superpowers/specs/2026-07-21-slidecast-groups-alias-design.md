# Slidecast v2 — 그룹 관리 · alias · 날짜 가독성 설계

- 날짜: 2026-07-21
- 상태: 설계 승인 대기 (유저 리뷰 게이트)
- 기반: 배포 완료된 Slidecast v1 (https://d2o39fnd1gcpgv.cloudfront.net,
  계정 123456789012 / us-east-1 / profile2)
- 선행 스펙: `2026-07-21-slidecast-viewer-design.md`

## 1. 목적

배포된 Slidecast 뷰어에 세 가지 기능을 추가한다.

1. **그룹 관리** — 덱을 그룹(폴더식)으로 묶어 갤러리에서 필터링. 그룹
   생성/삭제, 덱의 그룹 배정/해제.
2. **alias** — 덱마다 기억하기 쉬운 짧은 URL 슬러그를 부여해 `/s/{alias}`로
   바로 재생/공유.
3. **날짜 가독성** — 갤러리 카드·버전 목록의 ISO `updatedAt`을 사람이 읽기 쉬운
   `YYYY-MM-DD`로 표기.

추가로 기존 검색 필터에 alias를 포함하고, 그룹 필터와 검색을 결합한다.

## 2. 범위

포함:
- DDB에 그룹 메타 아이템 + 덱의 `group`/`alias` 필드 + GSI `byAlias`
- 그룹 CRUD API, 덱 그룹/alias 배정 API, alias 리졸브 API
- 뷰어: 그룹 사이드바/필터, 그룹 추가/삭제 UI, 덱 카드의 그룹 이동·alias 편집,
  `/s/{alias}` 재생 라우트, 날짜 포맷 개선, 검색에 alias 포함
- 로컬 스킬: `--group` / `--alias` 업로드 옵션, 그룹 생성/삭제 서브커맨드

제외 (YAGNI):
- 덱 1개의 다중 그룹 소속(덱 1개 = 최대 1개 그룹으로 확정)
- 계층(중첩) 그룹
- 서버측 검색 API (개인 규모 → 클라이언트 필터 유지)
- alias의 로그인 없는 공개 접근 (로그인 사용자만; 공유는 로그인 전제)
- 슬라이드 HTML 자체에 날짜 주입 (원본 보존)

## 3. 데이터 모델 변경 (DynamoDB `SlideDecks`)

기존 테이블을 그대로 쓰되, 아이템 타입을 구분한다.

### 덱 아이템 (기존 + 필드 2개 추가)
- `type`: `"deck"` (신규 명시 필드; 기존 아이템은 마이그레이션 시 기본 deck으로 간주)
- `group`: string | null — 소속 그룹 ID. `null`이면 미분류.
- `alias`: string | null — 짧은 URL 슬러그. 전역 유일.
- (기존) `deckId, title, tags[], status, currentVersion, versions[], createdAt, updatedAt`

### 그룹 메타 아이템 (신규, 같은 테이블 공존)
- PK `deckId` = `GROUP#{groupId}` (덱 deckId와 네임스페이스 분리)
- `type`: `"group"`, `groupId`, `name`, `createdAt`
- `status`: `"active"` (GSI 참여를 위해; 그룹은 아카이브 개념 없음)

### GSI 추가
- **`byAlias`** (PK `alias`) — alias→덱 O(1) 리졸브 + 유일성 검사. `alias`가 없는
  아이템은 이 GSI에 나타나지 않는다(sparse index).
- 기존 `byUpdatedAt`(PK `status`, SK `updatedAt`)는 유지.

### 마이그레이션
- 기존 덱 아이템에는 `type`/`group`/`alias`가 없음. 조회 코드는 `type` 부재 시
  `"deck"`으로 간주하고, `group`/`alias` 부재는 `null`로 취급(방어적 기본값).
  별도 백필 스크립트는 선택(있으면 명시적, 없어도 동작).

## 4. API 추가 (기존 API Lambda에 라우트 추가)

- `GET /api/groups` — 그룹 목록 (type=group 아이템)
- `POST /api/groups {name}` — 그룹 생성. groupId = slugify(name). 중복 시 409.
- `DELETE /api/groups/{groupId}` — 그룹 삭제. 소속 덱은 `group=null`(미분류)로
  이동(덱 자체는 보존). 그룹 메타 아이템만 제거.
- `PUT /api/decks/{id}/group {groupId|null}` — 덱 그룹 배정/해제. groupId가
  존재하는 그룹인지 검증(없으면 400).
- `PUT /api/decks/{id}/alias {alias|null}` — alias 설정/해제.
  - slugify 후 예약어(`api, slides, thumbnails, s, assets, web`) 및 GSI 중복 검사.
  - 충돌 시 409, 예약어 시 400.
- `GET /api/resolve/{alias}` — alias→덱 상세(현재 버전 재생 URL 포함). GSI `byAlias`
  조회. 없으면 404.

기존 `GET /api/decks`:
- `?group={groupId}` 필터 옵션 추가(`__unassigned__`이면 group=null만).
- 응답에서 `type=group` 메타 아이템 제외(deck만 반환).

## 5. 뷰어 변경 (다크 시네마틱 유지)

- **그룹 사이드바**: 갤러리 좌측에 그룹 목록(전체 / 미분류 / 각 그룹). 클릭 시
  해당 그룹 덱만. 상단에 그룹 추가(+), 각 그룹에 삭제(확인 모달: "덱은
  미분류로 이동" 안내).
- **덱 카드 액션 추가**: "그룹 이동"(그룹 선택 드롭다운), "alias 편집"(입력 +
  중복/예약어 시 인라인 에러). 기존 재생/버전/삭제 액션 유지.
- **`/s/{alias}` 라우트**: 뷰어가 경로 감지 → 로그인 상태 확인 → `GET
  /api/resolve/{alias}` → 현재 버전 풀스크린 재생. alias 없으면 404 안내.
- **날짜 가독성**: `formatDate(iso)` 헬퍼로 카드·버전 목록 날짜를 `YYYY-MM-DD`
  표기. 슬라이드 HTML은 미변경.
- **검색 확장**: 기존 title + tags에 `alias` 포함. 그룹 필터가 걸린 상태 위에서
  검색어가 함께 동작(그룹 내 검색). 클라이언트 측 필터 유지.

## 6. 로컬 스킬 확장 (`slidecast-append`)

- 업로드 옵션: `--group <name>`(없으면 미분류; 존재하지 않는 그룹명이면 생성 후
  배정할지/에러낼지 — 기본은 자동 생성), `--alias <slug>`(중복/예약어 시 에러).
- 그룹 서브커맨드: `--new-group <name>`, `--del-group <groupId>`.
- alias/group 슬러그화는 기존 `slugify` 재사용.

## 7. 인프라 (CDK)

- DDB에 GSI `byAlias`(PK `alias`, sparse) 추가. `cdk deploy`로 기존 테이블에
  무중단 적용(RETAIN 정책 유지). GSI 1개 추가는 온라인 인덱스 빌드.
- Lambda 코드 자산 갱신 + CloudFront는 재배포로 반영. S3/Cognito 변경 없음.
- 그룹 메타는 같은 테이블이라 스키마 리소스 변경 없음.

## 8. 검증 · 엣지 케이스

- alias 유일성: GSI 조회로 설정 시 검사. 예약어 목록 하드코딩.
- 그룹 삭제 시 소속 덱 재배정: 삭제 핸들러가 `byUpdatedAt` GSI로 active/archived
  덱을 조회한 뒤 `group == groupId`인 덱만 골라 `group=null`로 갱신한다(개인 규모라
  전체 조회 후 필터로 충분; 별도 group GSI는 YAGNI). 그 후 그룹 메타 아이템 삭제.
- `GET /api/decks`가 그룹 메타 아이템을 절대 덱으로 반환하지 않도록 type 필터.
- 마이그레이션 무결성: type/group/alias 부재 아이템도 정상 렌더(기본값).

## 9. 성공 기준

- 그룹을 만들고 덱을 배정하면 갤러리 사이드바에서 그룹별로 필터된다.
- 그룹 삭제 시 소속 덱은 사라지지 않고 미분류로 이동한다.
- 덱에 alias를 설정하면 `/s/{alias}`로 접속해 로그인 후 바로 재생된다.
- 중복/예약어 alias는 거부된다.
- 카드·버전 목록 날짜가 `YYYY-MM-DD`로 읽기 쉽게 표시된다.
- 검색이 title·tags·alias를 매칭하고 그룹 필터와 결합된다.
- 로컬 스킬로 `--group`/`--alias`를 지정해 업로드할 수 있다.
- 기존 v1 덱(신규 필드 없음)도 정상 표시/재생된다.
