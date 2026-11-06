# Packwright 操作手冊

完整參考。第一次使用請先看 5 分鐘的[快速上手](./quickstart.zh-TW.md);所有設定項與預設值見
[configuration.md](./configuration.md)。介面是英文的,本文提到按鈕、頁面與欄位時一律用介面上的原文。

## 目錄

- [系統概覽](#系統概覽)
- [安裝](#安裝)
- [啟動與部署](#啟動與部署)
- [帳號:首次啟動、註冊與登入](#帳號首次啟動註冊與登入)
- [專案來源](#專案來源)
- [New build 精靈](#new-build-精靈)
- [建置過程](#建置過程)
- [產物與下載](#產物與下載)
- [Docker 輸出](#docker-輸出)
- [使用者、角色與權限](#使用者角色與權限)
- [個人安全設定](#個人安全設定)
- [安全性與信任模型](#安全性與信任模型)
- [資料、保留期限與備份](#資料保留期限與備份)
- [附錄:API 端點](#附錄api-端點)
- [常見問題](#常見問題)

---

## 系統概覽

Packwright 把專案打包成可以直接交付的東西:

| 類型 | 做什麼 | 產出 |
|---|---|---|
| **Backend** | 用 [Nuitka](https://nuitka.net/) 把 Python 編成執行檔 | 執行檔(External 模式另附 `libs/`) |
| **Frontend** | 用 npm / yarn / pnpm / bun 建置 | 靜態檔(`dist/`) |
| **Full stack** | 先建置前端,再把它當資料一起編進後端 | 執行檔 + 前端靜態檔 |

每一種都可以再選擇輸出成 Docker image(匯出為 `.tar.gz`)。來源可以是**伺服器上的本機路徑**,
或 **Git URL**(系統 clone、建立 `.venv`、打包,完成後清理工作區)。

整個系統是一個 FastAPI 行程加上 React 管理台:建置日誌經 WebSocket 即時串流,完成的建置連同
當時的完整設定保存在資料庫,隨時可以用同一份設定重新打包。

> ⚠️ **部署前先讀[安全性與信任模型](#安全性與信任模型)。** Packwright 會在伺服器上執行目標專案
> 的程式碼,所以「誰能建立建置」就等於「誰能在這台機器上執行指令」。

---

## 安裝

**環境需求**

| 項目 | 需求 |
|---|---|
| Python | 3.13 以上 |
| [uv](https://docs.astral.sh/uv/) | 管理後端依賴與各 Python 版本 |
| Node.js | 22.12 以上(建置管理台;前端專案的建置也需要) |
| C 編譯器 | Nuitka 需要(Linux 上一般是 gcc) |
| Docker | 選用,輸出 Docker image 時才需要 |
| pigz | 選用,多執行緒壓縮 Docker 匯出 |
| PostgreSQL | 選用;預設用 SQLite,不需要任何資料庫設定 |

**步驟**

```bash
git clone https://github.com/xianhong1208/packwright.git
cd packwright
uv sync                                   # 後端依賴
cd frontend && npm install && npm run build && cd ..
cp .env.example .env                      # 選用;全部用預設值可以不建
```

**各 Python 版本的 Nuitka 環境(建議)。** 編出來的執行檔與執行 Nuitka 的直譯器 ABI 綁定:專案的
依賴是 3.12 編的,就要用 3.12 的 Nuitka 來編。`scripts/setup_nuitka_venvs.sh` 會建立
`.venv-py312` / `.venv-py313` / `.venv-py314`,建置時依專案自動挑選;找不到對應版本時會退回服務
自己的直譯器,並在首頁(**On the bench**)顯示環境降級的警告。

```bash
./scripts/setup_nuitka_venvs.sh
```

資料庫 migration 在每次啟動時自動執行,不需要手動跑 `alembic`。

---

## 啟動與部署

### 直接啟動

```bash
uv run python main.py                     # 預設 http://0.0.0.0:5018
PORT=5019 uv run python main.py           # 換 port
```

或用 `./start.sh`:它會先建置管理台(`SKIP_FRONTEND=1` 跳過)、`uv sync`,再啟動;
`--host` / `--port` 可覆寫綁定位址。

> **建議從 Packwright 目錄啟動。** `data/`(資料庫、工作區、image 匯出)預設是相對於啟動目錄的,
> 從別的目錄啟動會變成一個全新的空資料庫;要從別處啟動,請把這幾個路徑設成絕對路徑。
> 自動產生的金鑰不受影響:它們寫在 `main.py` 旁邊的 `.env`,不論從哪裡啟動都會讀到。
> `start.sh` 與 systemd unit 都會先切到正確目錄。

### 常駐(systemd)

`deploy/packwright.service` 是範例 unit,調整其中的 `WorkingDirectory`、`ExecStart` 與 `PATH` 後:

```bash
cp deploy/packwright.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now packwright
journalctl -u packwright -f
```

範例以 root 執行,因為服務要編譯目標專案、寫工作區、呼叫 docker,而且 `.venv` 與 `.venv-py3XX`
的擁有者必須是執行服務的帳號(換帳號會讓 uv 的直譯器連結失效)。若改用其他帳號,上述目錄要一併
交給該帳號。

### 只能有一個 worker

任務狀態、WebSocket 連線與建置名額都在行程記憶體裡,**不能開多個 uvicorn worker**,第二個 worker
看不到第一個的任務。同時進行的建置數由 `MAX_CONCURRENT_BUILDS`(預設 3)限制,超過的會排隊。

### 放在反向代理後面

建議前面放一層 HTTPS 反向代理。注意兩件事:

- 設定 `TRUSTED_PROXY_IPS` 為代理的位址,否則所有使用者都會被當成代理那一個 IP,限流會過嚴
  (細節見[安全性與信任模型](#網路與限流))。
- 代理要轉送 WebSocket(`/ws/`),建置日誌才會即時更新。

---

## 帳號:首次啟動、註冊與登入

### 首次啟動

資料庫裡還沒有任何使用者時,啟動會自動建立管理員:

- 帳號名稱是 `BOOTSTRAP_ADMIN_USERNAME`(預設 `admin`)。
- `BOOTSTRAP_ADMIN_PASSWORD` **未設定**時,密碼隨機產生,只在啟動 log 印一次:
  `Created bootstrap admin 'admin' with generated password: …`。
- 設成某個值則使用該密碼;**設成空字串**則不建立,改由第一個自行註冊的人成為管理員。

登入後請從左下角頭像選單的 **Security** 改密碼。

### 自行註冊與核准

登入頁的註冊功能永遠開放,但除了資料庫中的第一個帳號,**新註冊的帳號都是停用狀態**,登入會得到
「not active yet」。管理員在 **Users** 頁把帳號改成啟用才算核准。這是刻意的設計:核准帳號就是授予
在伺服器上執行程式碼的能力,見[信任模型](#核心假設建立建置--這台機器的-shell)。

### 登入與工作階段

- Access token 15 分鐘到期,前端會自動換新;登入狀態最長 7 天,勾選 **Remember me** 則 30 天。
- 密碼至少 6 個字元。
- **Forgot password**:設定過安全問題的帳號可以自行重設;沒有設定的要請管理員重設。

### 以 MCP Gate 登入(選用)

設定 `MCP_OAUTH_ENABLED=true`、`MCP_GATE_URL`、`MCP_OAUTH_CLIENT_ID` 等(見
[configuration.md](./configuration.md#mcp-gate-single-sign-on))後,登入頁會多一個
**Sign in with MCP Gate**。帳號本機密碼登入仍然可用。以 SSO 第一次登入的人會得到一個本機帳號,
同樣要等管理員核准;系統只依 MCP Gate 的使用者識別碼對應帳號,**不會**用 email 去綁定既有帳號。

---

## 專案來源

### 本機路徑(Local path)

專案已經在伺服器上時使用。只能讀取 `LOCAL_SOURCE_ROOTS` 列出的目錄底下(逗號分隔的絕對路徑;
解析符號連結後判斷)。**未設定時本機模式停用**,只能用 Git URL。

```ini
LOCAL_SOURCE_ROOTS=/srv/projects,/data/builds
```

本機模式在原地建置,產物寫進專案底下的輸出目錄(預設 `dist`)。External 模式會暫時在進入點檔案
插入一小段載入 `libs/` 的程式碼,建置結束後還原。

### Git URL

1. **驗證網址**:只接受 `http(s)`;拒絕網址內嵌帳密、`localhost`,以及指向 loopback、私有網段、
   link-local 的位址。內網 Git 伺服器要加進 `GIT_ALLOWED_HOSTS` 才能使用。
2. **列出分支與標籤**,選一個 ref。
3. **淺層掃描**:不必完整 clone 就能讀出頂層目錄與 `pyproject.toml` 的 `[dependency-groups]`,
   讓你直接勾選要打包的目錄。
4. 開始建置後 **clone 並建立 `.venv`**(`GIT_AUTO_VENV=true` 時跑 `uv sync`)。
5. 完成後依[保留期限](#資料保留期限與備份)清理工作區。

### Git 憑證(私有 repo)

管理員在左側工具列的 **Git credentials** 設定存取權杖(需要 `user:manage` 權限):

- 供應商可選 **GitHub**、**GitLab** 或 **Other (self-hosted)**;每個主機一組。
- 權杖用 `SETTINGS_ENCRYPTION_KEY` 加密儲存,API 不會回傳,介面只顯示末四碼。
- clone 時依網址的主機自動選用,只在呼叫 git 的那一刻以 HTTP header 的形式交給 git,
  不會寫進網址、資料庫的建置設定或日誌。
- `.env` 的 `GITLAB_TOKEN` 仍可作為後備,但只會送給 `GITLAB_TOKEN_HOST`(預設 `gitlab.com`)。

使用者**不需要也不應該**把帳密寫進 Git URL,這種網址會被驗證擋下。

---

## 專案與版本(Projects)

每次建置都會歸到一個**專案**:建置時指定的專案,或「名稱相同、來源(資料夾路徑或 Git URL)也相同」的
既有專案;找不到就在第一次建置時自動建立。同名但來源不同的會變成「名稱 (2)」,不會把兩份程式碼的建置
混在一起。升級到這個版本時,既有的建置紀錄會用同樣的規則自動歸檔。

- **Projects** 頁列出所有專案,最近有建置的在前。
- 專案頁依**版本**列出建置:每個版本的最新結果、建置次數,以及下載該版本最後一次成功的產物。
- **Build a new version**:Git 專案可以選 branch 或 tag;版本會自動讀出(tag 本身、`pyproject.toml` 的
  `[project].version`、或 `package.json` 的 `version`),可以修改;打包方式、單檔或資料夾、試跑、Docker
  可以只改這一次。這個版本以前成功過的話會提醒(仍然可以照建)。
- 專案由所有有建置權限(`task:create`)的人共用;改名、刪除限建立者與有 `project:manage` 權限的人。
  刪除專案不會刪掉它的建置。

版本會被蓋進產物:下載檔名(`shop-1.2.0.tar.gz`)、Docker image 的 tag(`shop:1.2.0`,並加上
`org.opencontainers.image.version` label 與 `PACKWRIGHT_BUILD_VERSION` 環境變數),以及 `VERSION` 檔
——放在產物旁邊,也包進執行檔裡(程式可以用 `os.path.join(os.path.dirname(__file__), "VERSION")` 讀到)。
純前端建置會把 `VERSION` 放進輸出目錄,部署後可以從 `/VERSION` 看到。

## New build

左側工具列或頂端的 **New build**。

### 快速建置

一打開就是快速建置:只要填來源(伺服器上的資料夾,或 Git repo 網址加分支),系統會讀專案結構
(本機用 `/api/git/diagnose`,Git 用 scan-tree 的檔案清單,兩者是同一套判斷):

- 有 Python 進入點(`main.py`、`app/main.py`、`src/main.py`、`run.py`)或 `pyproject.toml` → 後端
- 有 `package.json`(根目錄或 `frontend/`)→ 前端,前端目錄就是 `package.json` 所在處
- 兩者都有 → 全端

偵測結果會逐項出現在「What Packwright found」;類型認錯可以當場點選更正,認不出來時必須自己選一次
才能開始(不會默默用預設值建置)。使用者自己改過的欄位不會被偵測結果覆蓋。

**Settings** 區塊:打包方式、單一檔案或資料夾、試跑、Docker image 可以當場改;其餘設定列出目前的值,
**Change** 會開完整精靈並停在那個設定所在的步驟。來源讀不到(不在 `LOCAL_SOURCE_ROOTS`、不存在、Git
存取失敗)時直接顯示伺服器給的原因,不會被當成「認不出專案」。按 **All settings** 進入
完整精靈,已偵測的值都會帶過去;重新建置一律直接開完整精靈。

### 完整精靈

步驟依專案類型而定:

| 專案類型 | 步驟 |
|---|---|
| Backend (Python) | Basics → Backend → Docker → Review |
| Frontend | Basics → Frontend → Docker → Review |
| Full stack | Basics → Backend → Frontend → Docker → Review |

只有 Basics 是必填的,其他步驟保持預設就能建置。填到一半離開,草稿會自動保存(密鑰類欄位如
Docker 環境變數除外),回來時還原;**Clear draft** 可以清掉。

### Basics

| 欄位 | 說明 |
|---|---|
| Project name | 顯示用名稱 |
| Project type | Backend / Frontend / Full stack |
| Source | **Local path** 或 **Git URL** |
| Project path | Local 模式:伺服器上的絕對路徑(須在 `LOCAL_SOURCE_ROOTS` 底下) |
| Git URL / ref | Git 模式:repo 網址與分支或標籤 |

### Backend

| 欄位 | 說明 |
|---|---|
| Python version | 預設自動偵測。偵測依據是專案 `.venv` 裡編譯好的 `.so` 的 ABI 標籤,而不是宣告檔 |
| Entry point | 主程式,相對於專案根目錄(預設 `main.py`) |
| Binary name | 執行檔名稱;留空時取進入點的檔名(`main.py` → `main`) |
| Nuitka pack mode | **External**(建議):第三方套件放在執行檔旁的 `libs/`,編譯快;**Full**:全部編進執行檔,非常慢 |
| Single-file binary | 輸出單一執行檔或資料夾 |
| Dependency group | `[dependency-groups]` 中的一組(例如不同平台的 PyTorch) |
| CPU jobs | 平行編譯的程序數。0 = 自動:單獨建置時用全部核心,同時有多個建置時平分核心(每個至少 4)。記憶體用量幾乎跟它成正比 |
| Include packages | Nuitka 偵測不到的動態 import(例:`litellm, openai`) |
| Include package data | 套件內建的非 `.py` 資料檔(例:`certifi`) |
| Output directory | 輸出目錄,相對於專案(預設 `dist`) |
| Extra / data directories | 一起打包的原始碼目錄或資料目錄(輸入路徑後系統會建議) |
| Shrink binary | 移除不需要的相依,主要對 Full 模式有感 |
| Compilation report | 產生 Nuitka 編譯報告,查「執行時缺東西」時用 |
| Verify after build | 編完試跑一次執行檔(建議保持開啟) |

### Frontend

| 欄位 | 說明 |
|---|---|
| Frontend dir | 前端目錄,相對於專案 |
| Build tool | npm / yarn / pnpm / bun;有 lockfile 時以 lockfile 為準 |
| Build command | `package.json` 的 script 名稱(例:`build`、`build:prod`),只能是名稱,不能是任意指令 |
| Output dir | 前端建置的產出目錄(自動從 vite 設定偵測) |
| Env file / content | 建置前寫入的環境變數檔,建置後還原 |

輸入專案路徑後系統會自動偵測建置工具、指令與產出目錄並帶入;lockfile 沒有變動時,下次建置會跳過依賴安裝。

### Docker

不需要就保持關閉。開啟後可以設定 image 名稱、基底映像、對外 port、額外的 `RUN` 指令與環境變數。
純前端 + Docker 會包成 nginx image,可以再設定 API 反向代理與 nginx 參數,說明見
[快速上手的 nginx 一節](./quickstart.zh-TW.md#純前端--docker-的-nginx-設定-)。

### Review

確認全部設定後按 **Start build**,建置立刻排隊,頁面跳到該建置的詳情頁。

---

## 建置過程

詳情頁上方顯示目前狀態,後端建置另有階段進度條:

```
Queued → Preflight → Compile → Bundle → Verify
```

| 階段 | 做什麼 |
|---|---|
| **Queued** | 等待建置名額(`MAX_CONCURRENT_BUILDS`) |
| **Preflight** | 檢查專案路徑、進入點、`.venv`、Nuitka 與 Python 版本;有問題立刻失敗,不用等編譯 |
| **Compile** | Nuitka 編譯 |
| **Bundle** | 複製依賴(`libs/`)與資料目錄 |
| **Verify** | 試跑執行檔。缺模組會判定失敗;因為建置機沒有 GPU、連不到資料庫、缺命令列參數或授權檔而結束的,判定為警告,並說明這屬於執行環境而非打包問題 |

- **日誌** 經 WebSocket 即時串流,可搜尋、複製、下載。每個建置保留最後 `MAX_LOG_LINES` 行。
- **Cancel run** 會停止建置行程。
- 完成後的 **Build result** 卡片顯示產物大小、檔案數、SHA-256(單一檔案時)、驗證結果與耗時。
- **Rebuild** 帶著原本的設定回到精靈。

### 失敗時

詳情頁會說明三件事:**在哪個階段失敗**、**自動診斷**(認得的失敗會說明原因與修法,有些附一鍵修正,
例如 **Rebuild with auto-detect**)、以及**日誌中的關鍵錯誤行**。即使系統認不出原因,也一定會有階段與
錯誤行;把它們連同建置連結交給管理員就夠了。

### 任務連結

執行中與剛完成的建置在記憶體裡,網址是 `/task/<id>`;服務重啟或淘汰後,同一個連結會自動轉到
**Builds** 頁裡保存的紀錄(`/history/<id>`)。

---

## 產物與下載

| 類型 | 產物 | 從哪裡下載 |
|---|---|---|
| Backend / Full stack | 執行檔(+ `libs/`、資料目錄) | 建置當下即時打包成 `.tar.gz` 串流下載 |
| Frontend | 靜態檔 | 同上 |
| Docker | image 的 `.tar.gz` | `DOCKER_IMAGES_DIR/<task-id>.tar.gz`,可續傳 |

- 在詳情頁或 **Builds** 頁按 **Download output**。瀏覽器原生下載,不會先把整個檔案讀進網頁記憶體。
- 實作上前端先換一張**下載票證**(30 分鐘有效、只綁定這個建置與這個使用者、不能呼叫其他 API),
  兌換時會重新檢查帳號是否仍啟用、權限是否仍在。
- 非 Docker 產物是從工作區或專案的輸出目錄即時打包的,所以**工作區被清掉後就無法下載**:
  Git 模式的成功建置預設保留 `WORKSPACE_SUCCESS_TTL_DAYS`(7 天)。
- 腳本可以直接呼叫 `GET /api/history/{id}/download`(帶 `Authorization` header)。

---

## Docker 輸出

流程(以 Full stack + Docker 為例):

```
前端建置 → Nuitka 編譯(在主機上) → 產生 Dockerfile → docker build → docker save → .tar.gz
```

- 專案的 `.env` **不會**被打包進 image;執行容器時用 `--env-file` 或 `-e` 傳入。
- 資料目錄會被 `COPY` 進 image。
- 安裝 `pigz` 時以多執行緒壓縮(`DOCKER_EXPORT_COMPRESS_THREADS`),否則退回單執行緒 gzip。
- image 檔保留 `DOCKER_IMAGES_TTL_DAYS`(預設 30 天)。

```bash
docker load -i my-service.tar.gz
docker run --rm --env-file .env my-service:latest
```

---

## 使用者、角色與權限

### Users(需要 `user:view`)

查看帳號、狀態、角色、最後登入與登入記錄;有 `user:manage` 可以變更角色、啟用或停用帳號
(**核准新註冊就在這裡**),有 `user:reset_password` 可以替使用者設定新密碼。
系統不允許權限較少的人修改權限比自己多的帳號。

### Roles(需要 `role:view` / `role:manage`)

預設角色:

| 角色 | 權限 |
|---|---|
| `admin` | `*:*`(全部) |
| `user` | `task:create`、`task:view_own`、`task:cancel_own`、`history:view_own`、`history:export` |

自訂角色時可以指定**父角色**繼承其權限。權限碼:

| 權限 | 說明 |
|---|---|
| `task:create` | 建立建置(也用於精靈裡的目錄瀏覽、專案分析、Git 掃描) |
| `task:view_own` / `task:view_all` | 查看自己的 / 所有人的進行中建置 |
| `task:cancel_own` / `task:cancel_all` | 取消自己的 / 所有人的建置 |
| `history:view_own` / `history:view_all` | 查看自己的 / 所有人的建置紀錄 |
| `history:export` | 匯出 CSV(範圍依 view 權限) |
| `user:view` | 查看使用者與角色列表 |
| `user:manage` | 變更角色、啟用/停用帳號、管理 Git 憑證 |
| `user:reset_password` | 重設他人密碼 |
| `role:view` / `role:manage` | 查看 / 管理角色 |

萬用字元 `resource:*`、`*:action`、`*:*` 也可以使用。

---

## 個人安全設定

左下角頭像選單 → **Security**:

- **Change password**:需要目前的密碼。
- **Security question**:設定後可以透過 **Forgot password** 自行重設密碼。
- **Active sessions**:列出所有登入中的裝置,目前這一個標示 **This device**;其他的可以逐一登出,或按 **Sign out of all devices**。
- **Login history**:自己的登入紀錄(時間、IP、裝置、成功或失敗)。

---

## 安全性與信任模型

### 核心假設:建立建置 ≈ 這台機器的 shell

Packwright 的工作就是**執行目標專案的程式碼**:Git 模式會 clone 任意 repo 並執行 `npm install` /
`npm run build`(也就是對方 `package.json` 裡的 scripts),驗證階段會直接執行編出來的執行檔。
這對任何 build server 都是本質性的。結論是:

> **擁有 `task:create` 的使用者,實質上擁有以服務帳號在這台伺服器上執行指令的能力。**

所以真正的安全邊界是**帳號核准**,而不是打包流程裡的檢查:

- 除了第一個帳號,所有註冊都需要管理員核准;預設的 `user` 角色就有 `task:create`。
  核准帳號請當作「授予執行權」來看待。
- Git URL 驗證、本機路徑限制、subprocess 只用 argv、權杖遮罩、限流都是縱深防禦,**不是沙箱**。
  例如 Docker 自訂指令的允許清單只比對開頭,擋手誤,擋不住刻意繞過。

請把 Packwright 跑在隔離的主機上。完整說明與回報漏洞的方式見 [SECURITY.md](../SECURITY.md)。

### 建置設定裡的環境變數

使用者常把正式環境的 `.env` 內容貼進建置設定(前端 env、Docker 環境變數),這些內容會隨建置紀錄
永久保存,並**原樣**顯示給看得到該紀錄的人,讓別人能照著重現一個能跑的建置。能看別人紀錄的角色
本來就能建立建置,所以遮罩擋不住什麼,反而會產生壞掉的重建。請據此決定誰能拿到 `history:view_all`,
並保護好資料庫與備份。

### 密鑰

| 密鑰 | 位置 | 說明 |
|---|---|---|
| `JWT_SECRET_KEY` | `.env` | 簽發登入 token;未設定時首次啟動產生並寫入 `.env` |
| `SETTINGS_ENCRYPTION_KEY` | `.env` | 加密 Git 憑證;未設定時自動產生。**遺失後已存的憑證無法解密** |
| Git 憑證 | 資料庫(加密) | 見 [Git 憑證](#git-憑證私有-repo) |
| `DB_PASSWORD` / `DATABASE_URL` | `.env` | 使用 PostgreSQL 時 |

`.env` 必須是 `chmod 600`(系統寫入產生的密鑰時會設定)。若它曾經對其他帳號可讀,請輪替
`JWT_SECRET_KEY`:刪掉那一行再重啟,會產生新的金鑰,代價是所有人被登出一次。

### 網路與限流

- `X-Forwarded-For` 可以被用戶端任意偽造。**`TRUSTED_PROXY_IPS` 為空時完全不採信**,一律用實際連線
  位址;只有實際連線來自列出的代理時才採信,而且取**最右邊**的值(nginx 是把真實位址附加在後面)。
- uvicorn 內建的 proxy headers 處理刻意關閉,`TRUSTED_PROXY_IPS` 是唯一的判斷點。放在代理後面卻沒設定
  時,所有人會被算成同一個 IP、限流過嚴:這是刻意選擇的失敗方向,會立刻被發現,而不是靜默失效。
- 登入、註冊等端點有限流;送出建置(`POST /api/tasks`)另有每分鐘上限 `BUILD_SUBMIT_PER_MINUTE`。
- 登入記錄與稽核日誌的 IP 走同一套判斷,攻擊者無法在登入歷史裡寫入任意 IP。

### WebSocket 認證

access token 以子協定傳遞,不放在網址(網址會進 access log 與代理 log):

```js
new WebSocket(url, ['bearer', accessToken])
```

舊版用戶端的 `?token=` 查詢參數目前仍被接受,但不建議使用。

---

## 資料、保留期限與備份

### 資料位置

預設全部在啟動目錄下的 `data/`:

```
data/
├── build_center.db     # SQLite 資料庫(使用者、角色、建置紀錄、Git 憑證)
├── workspace/          # Git 模式每個建置一個目錄
└── docker_images/      # 匯出的 image,<task-id>.tar.gz
```

可以用 `DATABASE_URL`、`GIT_WORKSPACE_DIR`、`DOCKER_IMAGES_DIR` 搬到其他磁碟(見 README 的
「儲存與資料」)。`GIT_WORKSPACE_DIR` 與 `BOOTSTRAP_UV_CACHE_DIR` 放在同一個檔案系統,uv 才能用
硬連結而不是複製。

### 自動清理

背景排程每 `WORKSPACE_CLEANUP_INTERVAL_HOURS` 小時執行一次:

| 對象 | 保留 |
|---|---|
| Git 模式成功建置(非 Docker) | 完成時立刻只留下輸出;`WORKSPACE_SUCCESS_TTL_DAYS`(7 天)後刪除。**這也是可下載的期限** |
| Git 模式成功建置(Docker) | 完成時立刻刪除工作區(image 檔已另存) |
| 失敗 / 取消的建置 | `WORKSPACE_FAILED_TTL_DAYS`(30 天),留著方便除錯 |
| 找不到對應紀錄的目錄 | `WORKSPACE_ORPHAN_TTL_DAYS`(2 天) |
| Docker image 檔 | `DOCKER_IMAGES_TTL_DAYS`(30 天) |
| 過期的 refresh token | 失效後 `REFRESH_TOKEN_RETENTION_DAYS`(7 天) |

建置紀錄本身永久保存。

### 備份

資料庫裡有無法從程式碼重建的東西:建置紀錄(含每次的完整設定)、使用者與角色、稽核與登入紀錄。
工作區與產物有 TTL,重跑建置就會回來;這些不會。

`scripts/backup_db.sh` 會用服務本身的設定找到資料庫(`DATABASE_URL` → `DB_*` → 預設的 SQLite 檔),
SQLite 與 PostgreSQL 都支援,適合放進 cron:

```bash
bash scripts/backup_db.sh                                   # 存到 ./data/backups,保留 30 天
BACKUP_DIR=/mnt/nas/packwright RETENTION_DAYS=60 bash scripts/backup_db.sh
```

- **SQLite**:用 SQLite 的線上備份,服務執行中也能取得一致的快照,輸出 `<name>-<時間>.sqlite.gz`。
- **PostgreSQL**:用 `pg_dump`(需安裝),輸出 `<資料庫>-<時間>.sql.gz`;密碼經環境變數傳遞,不會出現在命令列。
- 只有備份成功後才會刪除超過 `RETENTION_DAYS` 的舊備份,失敗時以非零狀態結束。

還原前先停止服務:

```bash
gunzip -c build_center-<時間>.sqlite.gz > data/build_center.db        # SQLite
gunzip -c packwright-<時間>.sql.gz | psql -h HOST -U USER -d DBNAME    # PostgreSQL
```

備份檔含密碼雜湊與使用者貼進建置設定的環境變數,請限制存取權限。

---

## 附錄:API 端點

「權限」欄:*公開* 不需登入;*登入* 只需有效的 access token;其餘為需要的權限碼(`A / B` 表示
有其一即可,只有 `*_own` 的人只看得到自己的資料)。互動式文件在 `/docs`。

### 認證 `/auth`

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| GET | `/auth/check-first-user` | 公開 | 是否還沒有任何使用者 |
| POST | `/auth/register` | 公開 | 註冊;第一個帳號以外需要核准 |
| POST | `/auth/login` | 公開 | 登入 |
| POST | `/auth/refresh` | 公開(refresh token) | 輪替 refresh token、取得新的 access token |
| POST | `/auth/logout` | 登入 | 登出目前工作階段 |
| POST | `/auth/logout-all` | 登入 | 登出所有工作階段 |
| GET | `/auth/me` | 登入 | 目前使用者與權限 |
| POST | `/auth/change-password` | 登入 | 變更密碼 |
| PUT | `/auth/security-question` | 登入 | 設定安全問題 |
| POST | `/auth/forgot-password` | 公開 | 開始重設密碼,回傳安全問題 |
| POST | `/auth/verify-security-answer` | 公開 | 驗證答案,取得重設 token |
| POST | `/auth/reset-password` | 公開(重設 token) | 完成重設 |
| GET | `/auth/login-history` | 登入 | 自己的登入紀錄 |
| GET | `/auth/active-sessions` | 登入 | 自己的工作階段 |
| DELETE | `/auth/sessions/{id}` | 登入 | 登出指定工作階段 |
| GET | `/auth/oauth/mcp/status` | 公開 | 是否提供 MCP Gate 登入 |
| GET | `/auth/oauth/mcp/login` | 公開 | 開始 MCP Gate 登入 |
| GET | `/auth/oauth/mcp/callback` | 公開 | MCP Gate 回呼 |
| POST | `/auth/oauth/mcp/exchange` | 公開(一次性代碼) | 兌換 SSO 登入 |

### 建置 `/api`

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| POST | `/api/tasks` | `task:create` | 送出建置 |
| GET | `/api/tasks` | `task:view_own / task:view_all` | 進行中的建置 |
| GET | `/api/tasks/{id}` | 同上 | 單一建置(只在記憶體中的) |
| GET | `/api/tasks/{id}/logs` | 同上 | 日誌快照 |
| DELETE | `/api/tasks/{id}` | `task:cancel_own / task:cancel_all` | 取消建置 |
| GET | `/api/history` | `history:view_own / history:view_all` | 建置紀錄 |
| GET | `/api/history/{id}` | 同上 | 單筆紀錄(含設定與結果) |
| GET | `/api/history/users` | `history:view_all` | 有紀錄的使用者 |
| GET | `/api/history/export` | `history:export` | 匯出 CSV |
| POST | `/api/history/{id}/download-ticket` | `history:view_own / history:view_all` | 換取下載票證 |
| GET | `/api/download/{ticket}` | 票證 | 下載產物(瀏覽器用) |
| GET | `/api/history/{id}/download` | `history:view_own / history:view_all` | 下載產物(header 認證,腳本用) |
| DELETE | `/api/history/{id}/workspace` | 同上 | 手動刪除 Git 建置的工作區 |

### 精靈輔助 `/api`

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| GET | `/api/system-info` | 登入 | CPU 數、可用的 Python 編譯版本 |
| GET | `/api/directories` | `task:create` | 列出本機子目錄 |
| GET | `/api/analyze-project` | `task:create` | 分析本機專案、建議要打包的目錄 |
| GET | `/api/pyproject-groups` | `task:create` | 讀取 `[dependency-groups]` |
| GET | `/api/detect-frontend-config` | `task:create` | 偵測前端建置設定 |
| GET | `/api/list-env-files` | `task:create` | 列出 `.env*` |
| GET | `/api/env-file` | `task:create` | 讀取 env 檔 |
| POST | `/api/git/refs` | `task:create` | 列出遠端分支與標籤 |
| POST | `/api/git/scan-tree` | `task:create` | 淺層掃描遠端目錄 |
| POST | `/api/git/preview-frontend` | `task:create` | 讀取遠端前端設定與 env 檔 |
| POST | `/api/git/diagnose` | `task:create` | 目錄結構檢查 |

### 使用者、角色與 Git 憑證

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| GET | `/api/users` · `/api/users/count` · `/api/users/{id}` | `user:view` | 使用者 |
| GET | `/api/users/{id}/login-history` | `user:view` | 該使用者的登入紀錄 |
| PUT | `/api/users/{id}/role` | `user:manage` | 變更角色 |
| PUT | `/api/users/{id}/status` | `user:manage` | 啟用 / 停用(核准) |
| POST | `/api/users/{id}/reset-password` | `user:reset_password` | 重設密碼 |
| GET | `/api/users/roles/list` · `/api/users/permissions/list` | `user:view` | 角色與權限列表 |
| GET | `/api/users/roles/{id}` | `role:view` | 單一角色 |
| POST · PUT · DELETE | `/api/users/roles[/{id}]` | `role:manage` | 管理角色 |
| GET · POST · PUT · DELETE | `/api/settings/git-credentials[/{id}]` | `user:manage` | Git 憑證 |

### 監控與其他

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| GET | `/api/monitoring/stats` | 登入 | CPU、記憶體、磁碟與編譯環境狀態 |
| GET | `/api/monitoring/build-stats` | `history:view_own / history:view_all` | 首頁的建置統計 |
| GET | `/health` | 公開 | 健康檢查與版本 |
| WS | `/ws/tasks` | `task:view_all` | 所有建置的即時串流 |
| WS | `/ws/tasks/{id}` | 建置擁有者或 `task:view_all` | 單一建置的日誌與進度(只推送連線後的增量,先用 `/logs` 取快照) |

---

## 常見問題

**啟動 log 裡找不到管理員密碼**
只有在資料庫沒有任何使用者時才會產生並印出一次。忘了的話:若還沒有別的管理員,刪掉資料庫
(全新安裝)重來,或設定 `BOOTSTRAP_ADMIN_PASSWORD` 後用新的資料庫啟動;已經有其他管理員就請他重設。

**註冊完登不進去**
新帳號需要管理員在 **Users** 頁啟用(頁面最上方的「waiting to be let in」)。

**每次重啟所有人都被登出、Git 憑證失效**
自動產生的金鑰沒能存下來:啟動 log 會有 `Could not save the generated …` 的警告,通常是
`main.py` 旁邊的 `.env` 不可寫入。修正權限,或自己在 `.env` 設定 `JWT_SECRET_KEY` 與
`SETTINGS_ENCRYPTION_KEY`。

**本機路徑被拒絕(403)或選不到目錄**
路徑必須在 `LOCAL_SOURCE_ROOTS` 底下;未設定時本機模式停用。

**內網 Git 伺服器被拒絕**
私有網段位址預設被擋,把主機加進 `GIT_ALLOWED_HOSTS`。

**首頁出現環境降級警告**
某個 Python 版本沒有專用的 Nuitka 環境,選到它時會用服務自己的直譯器編譯,產物可能在執行時壞掉。
執行 `scripts/setup_nuitka_venvs.sh`。

**驗證失敗,說缺某個模組**
Nuitka 沒抓到動態 import:把套件填進 **Include packages**,或關閉 anti-bloat 重試。

**執行時 `FileNotFoundError`,缺的是套件內建的資料檔**
把套件名稱填進 **Include package data**。

**編譯時記憶體不足**
降低 **CPU jobs**,或改用 External 模式。

**下載顯示 Output directory not found**
工作區已被清理(超過 `WORKSPACE_SUCCESS_TTL_DAYS`),重新建置一次。

**打包出來的前端 Docker 服務回 504**
是 nginx 的閒置逾時,不是後端當掉,見[快速上手的說明](./quickstart.zh-TW.md#逾時到底在算什麼這題最多人踩)。

**Docker 容器讀不到 `.env`**
`.env` 不會被打包進 image,執行時用 `--env-file` 傳入。
