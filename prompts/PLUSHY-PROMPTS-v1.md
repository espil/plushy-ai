# Plushy AI 프롬프트 팩 v1 - 디자인 컨셉을 feed하는 제작 프롬프트 (에셋 방)

기준일: 2026-11-08. 상위 기준: DESIGN-CONCEPT-v1.md. 사용법: 모든 생성은 아래 고정 컨셉 블록을 프롬프트 맨 앞에 붙이고, 클래스별 템플릿의 빈칸만 채워서 돌립니다. 컨셉 블록 없는 자유 프롬프트 결과는 제작으로 치지 않습니다.

## 고정 컨셉 블록 (모든 프롬프트 공통, 영문 그대로 앞에 붙입니다)

```
2.5D chibi game sprite art, one consistent artist style, flat cel shading with exactly 4 value steps, no gradients, no photorealistic texture, warm dark outline #2B2026 on every shape, master palette only: grass #62B237, foliage #BEC461 #878F41 #464F28, dirt #956C34, logwood brown #583D21, warm stone #716247 #7E6F4E, water teal #61C7B8, monster hide #966F53, grade colours #EBEEF0 #FACD50 #69DC82 #50B4FF #B482FF #FF5A4B #FFCD46 #FF96CD, never use pure black #000000, never use pure white #FFFFFF
```

## 네거티브 블록 (모든 프롬프트 공통)

```
photorealistic, 3d render, gradient shading, soft airbrush, blurry, extra limbs, extra fingers, deformed hands, text, watermark, logo, multiple characters (unless a sheet is requested), cropped body, pure black, pure white background clothing glare
```

## 시트 공통 규칙 (템플릿이 시트를 만들 때 함께 넣습니다)

```
a sprite sheet with exactly [N] frames in ONE horizontal row, evenly spaced, on a plain white background, every frame full body visible with margin, feet on the same ground line in every frame, same character, same proportions, same colours in every frame, no text, no other objects
```

## 템플릿 1 - 캐릭터 베이스 (동작 시트)

용도: 민머리 무표정 베이스의 방향별 동작. 조건 이미지로 옷 입은 정면 템플릿을 겁니다 (맨몸 스틸에 걸면 생성이 거부된 전례가 있어 옷 입은 템플릿을 씁니다).

```
[컨셉 블록] + [시트 규칙] + the same bald chibi boy, [front / side facing left / back] view, [stand idle loop / walk cycle / alert guard stance / jump pose / prone pose], bare head with no hair, completely blank face with no eyes, no eyebrows, no mouth, no facial features, wearing only a plain sleeveless undershirt and shorts, bare feet, head about one third of total height, head wider than the shoulders, short compressed arms and legs
```

## 템플릿 2 - 캐릭터 정적 파트 (제자리 제작)

용도: 앞모습 기준 파트 (머리, 얼굴, 하의, 신발, 무기). 조건 이미지로 베이스 템플릿을 걸고, 파트만 그 자리 좌표에 그립니다. 완성본과의 차이로 나누지 않습니다.

```
[컨셉 블록] + use the reference image as the exact canvas: keep the character, proportions and position identical, add ONLY [the part: a big messy dark navy hairstyle / grey baggy pants / dark chunky sneakers covering both feet completely / a light-blue ice longsword], draw nothing else new, change nothing else, plain white background
```

얼굴 파트 전용 문장: `add ONLY facial features: [amber eyes with eyebrows / mouth / blush], as separate simple marks, nothing else`.

## 템플릿 3 - 동작 파트 시트

용도: 동작하는 몸 시트에 조건을 걸어 그 동작을 따라가는 파트 시트를 뽑습니다.

```
[컨셉 블록] + [시트 규칙] + ONLY [a pair of grey baggy pants / dark chunky sneakers, one pair per pose / a dark navy hairstyle], [front / side / back] view, in the [N] poses of the character in the reference, following his [leg positions / head position] exactly in each pose, draw ONLY the [part], no body, no skin, no person
```

주의: 신발처럼 포즈마다 두 조각으로 갈라지는 파트는 후처리에서 성분 단위가 아니라 슬롯 단위로 자릅니다 (프레임 배정이 섞이는 결함의 방지책).

## 템플릿 4 - 무기 (이름이 형태를 정합니다)

용도: 무기 외형 규격 v1 실행용. 손잡이는 항상 손에 잡히는 위치에 두고, 손잡이 좌표를 매니페스트에 기록합니다. 등급은 색 장식과 FX로만 표현하고 형태는 바꾸지 않습니다.

```
[컨셉 블록] + a single [weapon lineage: one-handed sword and shield / two-handed greatsword / bow with a magic string and a conjured arrow, no quiver / staff with a crystal casting focus / short dagger], [element motif and palette family], clean silhouette readable at small size, handle grip clearly visible at one end, on a plain white background, no hands, no person, no text
```

FX는 별도 생성으로 분리합니다: `the same weapon, ONLY its glow effect layer: [grade colour] light aura and particles around the blade, on a plain black background, no weapon body`.

## 템플릿 5 - 몬스터 (종 베이스)

용도: 종 베이스 원본을 staff/principal 레벨로 새로 그릴 때. 색만 바꾼 파생은 최종본이 아닙니다.

```
[컨셉 블록] + [시트 규칙 또는 single pose] + a [creature description: silhouette first, e.g. heavy moss-covered rock golem with amber eyes], full body [side view facing left], feet on the ground line, hide colour from the master palette family, readable silhouette, game monster sprite, no rider, no background scenery
```

## 템플릿 6 - 주민/NPC 변형

용도: 주민은 플레이어와 같은 베이스와 결을 쓰고 텍스처만 다르게 합니다. 별도 NPC 화풍은 없습니다.

```
템플릿 2와 같은 방식. 베이스 템플릿에 조건을 걸고 [hair / top texture / bottom texture]만 바꿉니다. 비례와 베이스와 얼굴 구조는 플레이어와 동일하게 유지합니다.
```

## 템플릿 7 - 환경 스프라이트 (소품, 식생)

```
[컨셉 블록] + a single [prop: wooden signpost / fence segment / grass tuft card], game environment sprite, colours from the master palette only, 4-step cel shading, warm dark outline, plain white background, no characters, no text
```

연결형 소품 (울타리 등)은 끝단 형상을 함께 지시합니다: `both ends cut vertically at the exact middle of a post so copies tile seamlessly side by side`.

## 템플릿 8 - 스킬 아이콘

용도: 스킬 아이콘 규격 v1 실행용. 256 납품, 작업은 512에서 합니다.

```
[컨셉 블록] + a single game skill icon, [one verb-first subject: a sword slashing down / a shield blocking], subject fills 75 percent of the frame, at most 3 colours, thick warm dark outline, light from the top-left, plain flat background field in logwood shades, no text, no numbers, no letters, the motif must read as a silhouette at 32 pixels
```

링 (트리 구분)은 후처리에서 규격대로 입힙니다: 캐릭터 원, 무기 육각, 방어구 방패형 사각, 신발 아래 삼각. 등급 색은 링에만 씁니다.

## 생성 후 검사 (하나라도 어긋나면 에셋이 아닙니다)

• 팔레트: palette_check.py 적합률 92% 이상, 외곽선 위반 0
• 밀도: 월드 스프라이트 256 px/m ±10% (표시 크기 기준), 캐릭터 라인은 1024 캔버스 Ground Zero 정렬
• 실루엣: 32px 축소와 단색 실루엣에서 주제가 읽힐 것
• 캐릭터 파트: 재합성 게이트 (슬롯 순서로 겹쳐 승인된 샘플 룩과 일치), 파트 중심점이 베이스 프레임 자체의 흔들림 범위 안
• 샘플 게이트: 종류당 1종을 먼저 완성해 Han님 판정을 받고, 통과 전에는 확장하지 않습니다
