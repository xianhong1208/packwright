# Packwright 運作方式

[English](how-it-works.md) · [README](../README.zh-TW.md) · [全部設定項](configuration.md)

一個建置經過哪些步驟、大多數安裝會用到的設定、Packwright 把資料放在哪裡,以及 Git 憑證怎麼使用。所有設定與預設值見
[configuration.md](configuration.md)(英文)。

## 運作方式

```
管理台 (React + antd)  ──HTTP / WebSocket──▶  FastAPI
                                              │
   auth (JWT + RBAC) ── tasks ── monitoring   │
                                              ▼
                          build dispatcher ──▶ Nuitka / npm / Docker workers
                                              │  (git clone → uv sync → 打包)
                                              ▼
                          產物 + Docker image .tar.gz
```

- **來源。** 一個建置不是*本機路徑*(限制在 `LOCAL_SOURCE_ROOTS` 內)就是 *Git URL*。Git 模式會驗證 URL(拒絕 `file://`、`ssh://`、localhost、link-local、或帶帳密的 URL),clone 到指定 branch/tag,Python 專案還會先建 `.venv` 再打包。git 只會送出 Packwright 裡存的憑證,絕不使用伺服器帳號自己的 git 設定或登入。
- **Token 注入。** 私有 repo 會依主機查出對應 token、解密,只在那一次呼叫 `git` 時,以限定在該 repo 來源的 HTTP 認證 header 交給它(經由 `GIT_CONFIG_*` 環境變數,所以也不會出現在命令列)。不會出現在網址、保存的建置設定或日誌,API 也不會回傳。
- **併發。** `MAX_CONCURRENT_BUILDS` 以 semaphore 限制同時進行的建置(各種類型都算),其餘排隊;同一個本機資料夾的建置一次一個,等待時不佔名額;行程刻意單一 worker,因為任務狀態、WebSocket 連線與 build semaphore 都在行程記憶體裡。
- **清理。** 背景迴圈依狀態與時間刪除各任務工作區與匯出的 image,並可將成功建置的工作區縮到只剩產出。

## 大多數安裝會用到的設定

全部由環境變數驅動,沒有任何必填項。`.env.example` 列出常用的幾項,[docs/configuration.md](configuration.md) 列出全部設定。最重要的幾個:

| 變數 | 預設 | 說明 |
|---|---|---|
| `DATABASE_URL` | *(空 → SQLite)* | 預設用本機 SQLite 檔;設 `postgresql+asyncpg://…` DSN 則改用 PostgreSQL。 |
| `HOST` / `PORT` | `0.0.0.0` / `5018` | 綁定位址。 |
| `JWT_SECRET_KEY` | 自動 | Session 簽章金鑰;留空則首次啟動產生並寫入 `.env`。 |
| `SETTINGS_ENCRYPTION_KEY` | 自動 | 加密儲存的 Git token;留空則自動產生寫入 `.env`。 |
| `CORS_ORIGINS` | 開發埠 | 允許呼叫 API 的瀏覽器來源(CSV)。 |
| `GIT_WORKSPACE_DIR` | `./data/workspace` | clone 與建置工作區位置;每次非 Docker 建置的產物(含本機建置)都另存在這裡,下載也從這裡。 |
| `DOCKER_IMAGES_DIR` | `./data/docker_images` | 匯出的 Docker image(`.tar.gz`)寫入位置。 |
| `NUITKA_CACHE_DIR` | *(空 → `~/.cache/Nuitka`)* | Nuitka 的快取,包含讓重建變快的 ccache 儲存區。 |
| `LOCAL_SOURCE_ROOTS` | *(空)* | 本機來源可讀取的絕對路徑前綴(CSV);留空則停用本機模式。 |
| `UV_BIN` / `PRE_BUILD_PATH` | 自動 | uv 路徑與 subprocess PATH;留空自動偵測。 |
| `BUILD_ENV_PASSTHROUGH` | *(空)* | 額外讓建置看得到的主機環境變數(CSV)。建置只拿得到基本變數、proxy/CA 設定與工具設定(`NPM_CONFIG_*`、`DOCKER_*` 等),拿不到服務自己的密鑰。 |
| `MAX_CONCURRENT_BUILDS` | `3` | 同時進行的建置數,其餘排隊。 |
| `PUBLIC_URL` | *(空)* | 大家開啟 Packwright 用的網址;建置通知會用它附上建置頁面的連結。 |
| `TRUSTED_PROXY_IPS` | *(空)* | 可信任 `X-Forwarded-For` 的代理 IP;留空最安全。 |
| `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_PER_HOUR` | `300` / `6000` | 每個用戶端位址可以呼叫 API 的次數(同一個 NAT 或代理後面的人共用);登入、註冊與送出建置另有更嚴的上限。 |

## 儲存與資料

Packwright 所有狀態都寫在單一的 `data/` 目錄下。預設這些路徑是**相對於你啟動時的工作目錄**(執行 `uv run python main.py` 的位置),所以預設安裝會把資料全部放在專案內:

```
data/
├── build_center.db     # SQLite 資料庫(使用者、角色、歷史、Git 憑證)
├── workspace/          # 每個建置一個目錄:clone、.venv、以及編譯產物
└── docker_images/      # 匯出的 Docker image,檔名為 <task-id>.tar.gz
```

**建置完成後產物在哪:**
- **二進位 / 打包產物**(後端、前端、全端):留在該次建置的工作區 `data/workspace/<task-id>/`,管理台的 **Download** 按鈕就是從這裡串流下載。
- **Docker 輸出**:image 存成 `data/docker_images/` 下的 `.tar.gz`;之後用 `docker load -i <檔案>` 載入。

**搬移儲存位置**(例如換到更大的磁碟)——在 `.env` 設定絕對路徑後重啟:

```bash
GIT_WORKSPACE_DIR=/srv/packwright/workspace     # clone、建置、可下載的產物
DOCKER_IMAGES_DIR=/srv/packwright/docker_images # 匯出的 image tarball
# 資料庫也可一起搬(SQLite 檔,或改指向 PostgreSQL):
DATABASE_URL=sqlite+aiosqlite:////srv/packwright/build_center.db
```

把 `GIT_WORKSPACE_DIR` 和 `BOOTSTRAP_UV_CACHE_DIR` 放在同一個檔案系統,`uv` 安裝相依時才能用 hardlink 而非複製。

**保留期限**——背景清理會依 TTL 回收磁碟,避免無限成長。由於非 Docker 產物是從工作區下載的,成功 TTL 同時等於*產物可下載的期限*:

| 變數 | 預設 | 保留內容 |
|---|---|---|
| `WORKSPACE_SUCCESS_TTL_DAYS` | `7` | 成功的非 Docker 工作區(即產物可下載多久)。 |
| `WORKSPACE_FAILED_TTL_DAYS` | `30` | 失敗 / 取消的工作區(保留較久以便除錯)。 |
| `DOCKER_IMAGES_TTL_DAYS` | `30` | 匯出的 image tarball。 |

建置成功時工作區也會自動精簡:非 Docker 建置只留下產物(丟掉 clone、`.venv`、`.git`),Docker 建置則直接刪除整個工作區,因為 image tarball 已保存結果。

## Git 憑證

私有 repo 的存取權杖在管理台設定(左側工具列的 **Git credentials**,需要 `user:manage` 權限),不放在 `.env`:

- 每個主機一組,支援 **GitHub**、**GitLab** 或自架實例(任意主機)。
- 以 `SETTINGS_ENCRYPTION_KEY` 加密儲存,API 不回傳——介面只顯示末四碼。
- 建置 clone URL 時,自動選用主機完全相符的 token。
- `.env` 的 `GITLAB_TOKEN` 仍作為沒有相符憑證時的後備,但只會送給 `GITLAB_TOKEN_HOST` 指定的那一台主機(預設 `gitlab.com`;自架 GitLab 請設成該主機名稱)。

## 沿用 Build Center 的名稱

Packwright 在 v1.0.0 以前名為 *Build Center*。存在於既有資料中的名稱保留舊拼法,不需要任何遷移:SQLite 檔 `data/build_center.db`、預設的 PostgreSQL 資料庫 `build_center`,以及煙霧測試時執行檔仍會收到的 `BUILD_CENTER_SMOKE_TEST`(與新的 `PACKWRIGHT_SMOKE_TEST` 並存)。systemd unit 改為 `deploy/packwright.service`。
