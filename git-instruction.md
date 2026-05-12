# Git 协作规范指南 (Git Collaboration Guide)

为了保证团队开发的高效与代码库的整洁，请所有成员严格遵守以下 Git 协作流程。

## 1. 分支管理策略

我们采用类似 GitHub Flow 的分支模型，所有开发都在功能分支上进行，通过 Pull Request (PR) 合并到 `main` 分支。

### 1.1 分支命名规范

| 分支类型 | 格式 | 示例 | 描述 |
| :--- | :--- | :--- | :--- |
| **功能开发** | `feature/功能名` | `feature/login-module` | 新功能或重大改进 |
| **缺陷修复** | `fix/缺陷描述` | `fix/issue-123-crash` | 修复线上或测试中的 Bug |
| **文档更新** | `docs/文档名` | `docs/api-standard` | 仅涉及文档、注释的修改 |
| **性能优化** | `perf/优化项` | `perf/query-speed` | 提高性能的代码更改 |
| **重构** | `refactor/模块名` | `refactor/auth-logic` | 代码重构，不涉及功能变化 |

### 1.2 分支操作流程

1.  **同步主分支**：在创建新分支前，确保本地 `main` 是最新的。
    ```bash
    git checkout main
    git pull origin main
    ```
2.  **创建功能分支**：
    ```bash
    git checkout -b feature/your-feature-name
    ```
3.  **开发与提交**：在本地进行开发，并按照规范提交代码。
4.  **推送分支**：
    ```bash
    git push -u origin feature/your-feature-name
    ```

---

## 2. 代码提交规范 (Commit Message)

提交信息应清晰地描述“做了什么”以及“为什么做”。建议使用以下格式：

### 2.1 格式要求
`<type>(<scope>): <subject>`

-   **Type (必选)**：
    -   `feat`: 新功能
    -   `fix`: 修补 Bug
    -   `docs`: 文档变更
    -   `style`: 格式（不影响代码运行的变动）
    -   `refactor`: 重构
    -   `perf`: 性能优化
    -   `test`: 增加测试
    -   `chore`: 构建过程或辅助工具的变动
-   **Scope (可选)**：说明影响的范围（如：`auth`, `database`, `ui`）。
-   **Subject (必选)**：简短描述，不超过 50 个字。

**示例：**
-   `feat(auth): 增加企业微信扫码登录功能`
-   `fix(api): 修复飞书回调请求超时的问题`

---

## 3. 提交前的自检清单 (Pre-submission Checklist)

在推送代码或提交 PR 之前，请务必完成以下操作：

1.  **代码清理**：删除调试用的 `print`、`console.log` 或无用的注释。
2.  **本地运行**：确保代码在本地环境能正常编译/运行。
3.  **单元测试**：运行相关测试用例，确保现有功能无回归风险。
4.  **同步远程**：提交前先拉取 `main` 并合并（或变基），解决潜在冲突。
    ```bash
    git checkout feature/your-feature-name
    git fetch origin
    git merge origin/main
    # 解决冲突后
    git add .
    git commit -m "chore: 合并 main 分支最新更改"
    ```

---

## 4. 合并与 Pull Request (PR)

1.  **发起 PR**：在 GitHub 上将你的功能分支指向 `main` 发起 Pull Request。
2.  **代码评审 (Code Review)**：至少需要一名其他成员审核代码。
3.  **修改建议**：根据评审意见在本地修改后再次推送，PR 会自动更新。
4.  **合并与删除**：PR 通过后，使用 `Squash and Merge` 合并（保持主分支历史简洁），并删除远程功能分支。

---

## 5. 常用紧急操作

-   **撤销上一次提交（保留更改）**：`git reset --soft HEAD~1`
-   **修改上一次提交信息**：`git commit --amend`
-   **暂存当前更改**：`git stash` (当你需要紧急切换分支时)
