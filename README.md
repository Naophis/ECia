# Claude Code STM32G431 BLDC HIL Kit

STM32G431KBU6 + MP6540HA のセンサレス6-stepファームウェアを、デバッガーと実機を接続した状態で段階的に開発するためのClaude Code一式です。

承認済みMilestone内では、Claudeが次のループを継続します。

1. 観測
2. 検証可能な仮説を1つ設定
3. 最小変更を1つ実施
4. ビルド
5. 対象MCU・プローブを照合
6. halt状態で書き込み
7. duty・時間・RPMを制限した試験
8. 停止して証拠を保存
9. 判定して次の1変更へ進む

Milestone移行、上限緩和、配線変更、保護解除、観測不能、停止失敗では自動継続しません。

## 同梱物

| パス | 役割 |
|---|---|
| `CLAUDE.md` | Claudeが常時守る短いプロジェクト規則 |
| `docs/motor-control-spec.md` | 実装方針・Milestone・成功条件の完全版 |
| `.claude/skills/hil-loop/` | `/hil-loop N` で明示起動する実機ループSkill |
| `.claude/hooks/` | 直接書き込み・保護状態編集を遮断し、ループを監査 |
| `tools/hilctl` | build/identify/flash/test/stopを一元化する安全ラッパー |
| `tools/hilctl-user` | 人間だけが使う承認・再arm・上限変更ツール |
| `.hil/` | fail-closedの設定、上限、承認テンプレート |
| `tools/hil-adapters/` | hilctlが呼ぶローカルadapter（identify / flash / verify_halted / stop / test / build） |
| `tests/` | ラッパーとHookの回帰テスト |
| `docs/hardware-mapping.md` | 検証済みのGPIO / AF / TIM1 / COMP / ADC / クロック対応表と出典 |
| `docs/hil-abi.md` | ホストとファームウェアが共有する`hil_cmd` / `hil_state`の契約 |
| `docs/milestone-0-report.md` | Milestone 0の調査結果とMilestone 1実装計画 |

導入は [INSTALL.md](INSTALL.md) を参照してください。

## 重要

- `.hil/config.json`はMilestone 0でこの基板に合わせて設定済みです。
- `.hil/safety-policy.json`は人間の所有物です。Claudeは作成も編集もしません。`.hil/safety-policy.template.json`をコピーして配置してください。
- ソフトウェア保護は、物理電流制限、ロータガード、独立gate-disable、電源遮断手段の代替ではありません。
- 実機試験中は人が即座に電源を切れる状態を維持してください。
