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
- `.github/workflows/deploy.yml`: 30분마다 데이터 갱신 후 GitHub Pages 배포

## GitHub Secrets

레포의 `Settings -> Secrets and variables -> Actions`에 아래 값을 넣으면 소셜 수집이 켜집니다.

- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `X_BEARER_TOKEN`
- `YOUTUBE_API_KEY`

키가 없어도 시장 데이터와 숏비중 기반 모니터링은 계속 작동하며, 해당 소셜 소스는 `skipped`로 표시됩니다.

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
