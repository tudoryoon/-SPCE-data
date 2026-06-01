# SPCE Data Monitor

`$SPCE`의 현재 밈/숏스퀴즈 붐을 `$GME` 2021 국면과 비교하는 GitHub Pages 대시보드입니다.

## 사이트

배포 후 URL:

```text
https://tudoryoon.github.io/-SPCE-data/
```

## 구조

- `public/`: GitHub Pages로 배포되는 정적 대시보드
- `scripts/update_data.py`: 시장 데이터와 소셜 언급량을 수집해 `public/data/*.json` 생성
- `.github/workflows/deploy.yml`: 3시간마다 데이터 갱신 후 GitHub Pages 배포

## WSB 트렌딩 지표

WallStreetBets Top Trending Stocks 패널은 ApeWisdom의 공개 r/wallstreetbets mention ranking을 사용합니다. 기본 집계 범위는 24시간이며, Reddit OAuth 키가 있으면 최근 WSB 글/댓글 샘플에 rules-based BoW 감성 분류를 적용해 Positive / Negative / Neutral stacked bar로 표시합니다.

- Mention count: r/wallstreetbets에서 종목 티커가 언급된 수
- Positive: `calls`, `long`, `squeeze`, `moon`, `buy` 등 상승 방향성 단어가 우세한 글/댓글
- Negative: `puts`, `shorting`, `dump`, `sell`, `overpriced` 등 하락 방향성 단어가 우세한 글/댓글
- Neutral: 방향성이 없거나 긍정/부정이 섞인 글/댓글

Reddit 키가 없으면 mention ranking은 표시하되 감성 split은 neutral로 둡니다.

## GitHub Secrets

레포의 `Settings -> Secrets and variables -> Actions`에 아래 값을 넣으면 소셜 수집이 켜집니다.

- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `X_BEARER_TOKEN`
- `YOUTUBE_API_KEY`

키가 없어도 시장 데이터와 숏비중 기반 모니터링은 계속 작동하며, 해당 소셜 소스는 `skipped`로 표시됩니다.

## Pages 설정

워크플로는 `public/` 산출물을 `gh-pages` 브랜치에 발행합니다. GitHub Pages가 자동으로 열리지 않으면 레포의 `Settings -> Pages`에서 `Deploy from a branch`, 브랜치 `gh-pages`, 폴더 `/`를 선택하면 됩니다.

## 로컬 실행

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python .\scripts\update_data.py --window-hours 24
python -m http.server 8000 -d public
```

브라우저에서 `http://localhost:8000`을 열면 됩니다.

## 점수 기준

GME 2021 기준선은 SEC Staff Report의 `short interest as a percent of float reached 122.97%` 수치를 사용합니다. 유사도 점수는 투자 신호가 아니라 구조 비교용 리서치 지표입니다.
