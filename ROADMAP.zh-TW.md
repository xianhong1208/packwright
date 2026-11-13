# 發展路線圖

[English](ROADMAP.md)

Packwright 在 1.3 之後的方向。每一項寫的是使用者會得到什麼，而不是怎麼做出來。除非某項變更會造成不相容，否則每個版本都是
minor 版本。每一項在對應的 [milestone](https://github.com/xianhong1208/packwright/milestones) 下都有一個 issue。

## 已發布

**1.0.0（2026-09-10），第一版，當時叫 Build Center。** 用 Nuitka 編譯 Python，用 npm、yarn、pnpm 或 bun 建置前端，兩者可以打包
在一起，也能匯出成 Docker image；全部在有即時日誌、帳號與角色權限的網頁管理台完成。每個主機各一組 Git 憑證，預設用 SQLite，也能
透過 `DATABASE_URL` 改用 PostgreSQL，可選擇以 MCP Center（現在的 MCP Gate）登入。

**1.1.0（2026-11-06），改名為 Packwright 並重新設計。** 全新的管理台（首頁 *On the bench*、左側工具列、Ctrl/Cmd+K 快速跳轉）與
登入頁；不再有預設的管理員密碼；`docs/configuration.md` 列出所有設定；加入 CI 與 Dependabot；修正下載票證、Git 產物下載與
GitLab token 後備的安全問題。

**1.2.0（2026-11-06），專案與版本。** 建置歸檔到大家共用的專案，並記錄版本：版本從 Git tag、`pyproject.toml` 或
`package.json` 讀出，用在下載檔名、image tag 與 `VERSION` 檔。專案設定可以預覽建置會跑的指令；**快速建置**讀完資料夾或 Git URL
就能一鍵開始；建置結果可以通知到 Discord、Slack 或任何接收 JSON 的 webhook；用 ccache 做編譯快取；附上 Docker image 與
`docker compose` 設定，建置需要的工具都在裡面；同時進行的建置會分攤機器的核心。

**1.3.0（2026-11-09），建置看不到服務本身的密鑰。** 建置只拿得到基本變數、proxy 與 CA 設定、工具設定，以及
`BUILD_ENV_PASSTHROUGH` 列出的變數；前端測試偶發失敗的問題也一併修好。

**1.3.1（2026-11-09），全面檢查後的修正。** 變更角色不會再讓所有人都被鎖在外面；本機建置下載到的只會是那一次的產出；進入點必須
在專案裡；git 不會用到伺服器自己的 git 登入；一般瀏覽不會再撞到速率限制；等待資料夾的建置不再占用建置名額；Git 憑證的主機會先
檢查格式。

**1.3.2（2026-11-13），更新相依套件，修正角色設定。** 目前開著的相依套件更新一次套用，並用實際建置驗證（Nuitka 4.3.5、新版 FastAPI、SQLAlchemy 與 React 函式庫；lint 工具的 `minimatch` 漏洞已修正）。**Roles** 對話框可以清除角色的上層角色。

完整變更見 [CHANGELOG.md](CHANGELOG.md)。

## 接下來

| 版本 | 你會得到什麼 |
|---|---|
| **1.4：自動化** | **push 或打 tag 就建置：** 接收 GitHub、GitLab 與 Gitea 的 webhook，各自檢查簽章；其他來源可以用附 token 的通用網址。專案可以**排程建置**。**API token**：腳本與 CI 不用密碼就能啟動建置、下載產出。**repo 裡的 `packwright.toml`：** 專案可以把建置設定放在程式碼旁邊；檔案裡有的欄位以檔案為準，管理台會標出哪些值來自檔案。 |
| **1.5：產出與發布** | 每次建置都附上 **`SHA256SUMS`、manifest 與 CycloneDX SBOM**。每個專案**只保留最近 N 份產出**，**建置快取（Nuitka、uv、npm）有上限**並定期清理，磁碟不會一直長大。**建置成功後自動發布：** 檔案上傳到 GitHub 或 Gitea Releases，image 推到**任何 registry**（Docker Hub、GHCR、Gitea 或自架的）。這些 token 跟 Git 憑證一樣加密保存。 |
| **1.6：隔離** | 每個建置都**以獨立的使用者或在自己的容器裡**執行，讀不到服務的檔案，也讀不到其他建置。**每個專案自己的密鑰**，加密保存，只交給該專案的建置。 |
| **1.7：更多平台** | **遠端建置 agent**，支援 Windows、macOS 與 arm64，同一個管理台就能替這些平台建置。**程式碼簽章：** Windows 的 Authenticode，macOS 的簽章與公證（notarization）。 |

## 以後

- **放在 MCP Gate 後面的 MCP 介面。** 從 AI 用戶端啟動建置、追蹤進度、取得產出，由 MCP Gate 的 token 決定誰能做什麼。
