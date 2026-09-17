# STM32G431 + MP6540HA Sensorless BLDC Firmware 開発指示書

## Claude Codeへの最初の指示

この文書は、マイクロマウス吸引ファン用BLDCファームウェアの実装指示書である。

まずリポジトリ全体を調査し、**Milestone 0の調査結果とMilestone 1の実装計画だけを提示すること**。承認前にコードを変更してはならない。

デバッガーと実機は接続したまま運用する。Milestone 1以降は、承認されたMilestoneの範囲内で、Claude Code自身がbuild、flash、reset、実行、ログ・波形相当の観測、原因分析、修正を反復すること。各試行ごとの確認待ちは不要とする。ただし、次のMilestoneへ進む前には結果を報告し、承認を待つこと。

方針は次で固定する。

> **STM32G431 + MP6540HA専用**  
> **open-loop forced 6-step始動 → COMPによるBEMF zero-cross検出 → sensorless 6-step**

SimpleFOC、FOC、AM32、ESCape32は使用しない。まず100,000 rpm級まで確実に回ることを優先する。

---

## 1. 目的

STM32G431KBU6とMP6540HAを使用し、マイクロマウス吸引ファン用BLDCモーターを駆動する専用ファームウェアを実装する。

目標：

- 確実に始動する
- sensorlessで安定して回転する
- 約100,000 rpm以上まで安定動作する
- 3Sを基本とし、将来的に4Sも扱える
- 脱調時に暴走せず、安全に停止できる
- 最終的にDShot等から回転指令を与えられる

優先順位：

1. deterministicなタイミング
2. デバッグ可能性
3. 高速回転での安定性
4. 始動成功率
5. 機能追加

---

## 2. 基本アーキテクチャ

```text
STOP
 ↓
ALIGN
 ↓
FORCED 6-STEP
 ↓
OPEN-LOOP RAMP
 ↓
BEMF ACQUIRE
 ↓
SENSORLESS LOCK
 ↓
CLOSED-LOOP 6-STEP
 ↓
HIGH-SPEED RUN
```

低速ではBEMFが得られないため、強制転流で始動する。十分な回転数になったらBEMF zero-cross（ZC）を検出し、sensorless 6-stepへ移行する。

FOCは実装しない。

---

## 3. ハードウェア

### MCU

- STM32G431KBU6
- Cortex-M4 / 170 MHz
- 主に使用するperipheral：TIM1、general-purpose timer、COMP1、COMP2、ADC、DMA、EXTI

初期化にはHALを使用してよい。モーター制御の時間クリティカル部分にはLLまたはdirect register accessを使用し、HALの高レベルAPIを多用しない。

### Gate driver

使用デバイスは**MP6540HA**であり、MP6540Hではない。

High-side / Low-sideを独立制御する。

```text
HSA / LSA
HSB / LSB
HSC / LSC
```

MP6540H向けの`ENA/PWMA`等のモデルで実装しない。

---

## 4. Motor PWM pin assignment

回路図上の固定配線：

| Phase | High-side | Low-side |
|---|---|---|
| A | PA8 | PA7 |
| B | PA9 | PB0 |
| C | PA10 | PF0 |

想定するperipheral mapping：

| Signal | Pin | Peripheral |
|---|---|---|
| HSA | PA8 | TIM1_CH1 |
| LSA | PA7 | TIM1_CH1N |
| HSB | PA9 | TIM1_CH2 |
| LSB | PB0 | TIM1_CH2N |
| HSC | PA10 | TIM1_CH3 |
| LSC | PF0 | TIM1_CH3N |

したがって、以下の構成を前提とする。

```text
Phase A = TIM1 CH1 / CH1N
Phase B = TIM1 CH2 / CH2N
Phase C = TIM1 CH3 / CH3N
```

**実装前にSTM32G431KBU6のdatasheetとRM0440でAF mappingを再確認すること。回路図とMCU仕様に矛盾があれば、コードを書かず報告すること。**

---

## 5. TIM1使用方針

TIM1を3相bridge専用timerとする。

使用機能：

- CH1 / CH1N
- CH2 / CH2N
- CH3 / CH3N
- complementary PWM
- dead-time
- output preload
- COM event
- BREAK / emergency stop

6-step commutation時にGPIOを順番に書き換える実装は禁止する。各sectorの次状態をpreloadし、TIM1 COM event等で3相状態を同時更新することを優先する。

---

## 6. BEMF回路

各phase voltageは次の抵抗分圧を通している。

```text
Phase
 ↓
56 kΩ
 ↓
BEMF_x
 ↓
10 kΩ
 ↓
GND
```

MCU接続：

| Signal | Pin |
|---|---|
| BEMF_A | PA0 |
| BEMF_B | PA4 |
| BEMF_C | PA5 |

### Virtual neutral

```text
BEMF_A --47k--+
               |
BEMF_B --47k--+---- BEMF_N
               |
BEMF_C --47k--+
```

BEMF_NはPA1とPA3の両方へ接続されている。この二重接続は意図したものであり、変更しない。

---

## 7. ComparatorによるZero Cross検出

ADC pollingではなく、STM32G431内蔵COMPを優先して使用する。

第一候補：

```text
COMP1:
    BEMF_N vs BEMF_A / BEMF_B

COMP2:
    BEMF_N vs BEMF_C
```

想定：

| Floating phase | Comparison |
|---|---|
| A | BEMF_A vs BEMF_N |
| B | BEMF_B vs BEMF_N |
| C | BEMF_C vs BEMF_N |

COMP1のinput muxをA/Bで切り替え、C相はCOMP2を使用する構成を第一候補とする。

PA0、PA1、PA3、PA4、PA5について、RM0440のCOMP input muxを確認してから確定すること。推測でregisterを書かない。

---

## 8. Six-step commutation table

正転の基本sequence：

| Sector | Source/PWM | Sink/ON | Floating | Expected ZC |
|---:|---|---|---|---|
| 0 | A | B | C | C rising |
| 1 | A | C | B | B falling |
| 2 | B | C | A | A rising |
| 3 | B | A | C | C falling |
| 4 | C | A | B | B rising |
| 5 | C | B | A | A falling |

実際のmotor wire orderによって回転方向が逆になる場合はsequenceを反転する。

sector処理は大量のswitch文ではなく、テーブル駆動とする。

```c
typedef struct {
    Phase source;
    Phase sink;
    Phase floating;
    Edge expected_edge;
    Comparator comparator;
} CommutationSector;
```

### Bridge state

各sectorでは次の状態とする。

```text
Source phase:
    High-side = PWM
    Low-side  = OFF

Sink phase:
    High-side = OFF
    Low-side  = ON

Floating phase:
    High-side = OFF
    Low-side  = OFF
```

Floating phaseは必ず真のHi-Zにする。BEMF ZC検出中にfloating phaseへPWMを加えない。

---

## 9. PWMと高速回転要件

PWM frequencyは設定値として管理し、初期候補は24～48 kHzとする。

**PWM frequencyとcommutation frequencyは別物として扱う。commutationをPWM周期に同期させてはならない。**

14 pole / 7 pole-pair motorの例：

```text
100,000 rpm
mechanical frequency = 100000 / 60 ≈ 1667 Hz
electrical frequency = 1667 × 7 ≈ 11.67 kHz
commutation frequency ≈ 11.67 kHz × 6 ≈ 70 kHz
sector duration ≈ 14.3 µs
```

100,000 rpm級ではcommutation frequencyがPWM frequencyを超える可能性があるため、PWM ISRからcommutationする設計は禁止する。

高速ISR内で以下を実行しない。

- `printf`
- `HAL_Delay`
- blocking ADC
- `malloc`
- 重い浮動小数点演算

---

## 10. Startup

停止状態ではBEMFが存在しないため、始動は必ずopen-loopで行う。

```text
STOP
 ↓
ALIGN
 ↓
FORCED_COMMUTATION
 ↓
RAMP
 ↓
BEMF_ACQUIRE
```

ALIGNでは一定sectorへ小さいdutyを与え、rotor positionを既知方向へ寄せる。小型1103モーターなので過大なALIGN currentを流さない。ALIGN dutyとdurationは設定値にする。

### Forced commutation ramp

timerによる固定転流でsector 0～5を順に進め、sector periodを徐々に短くする。

```text
Tsector:
1000 µs → 800 → 600 → 400 → ... → sensorless acquisition region
```

具体値はmotorに合わせて調整可能にする。固定delay loopは禁止し、timer compareを使用する。

### Startup中のBEMF観測

open-loop ramp中もCOMPを監視する。ただし初期段階ではBEMFを制御に使わず、以下を記録する。

- commutation timestamp
- expected ZC time
- actual ZC timestamp
- phase error

これにより、rotorがforced commutationに追従しているか確認する。

---

## 11. Zero Cross detection

sectorごとにfloating phaseとexpected edgeが決まる。expected edge以外はrejectする。

例：

```text
Sector 0
A+ / B-
C floating
Expected: C rising
```

### Blanking

commutation直後のswitching noiseを避けるため、次の順序とする。

```text
COMMUTATION
 ↓
COMP IGNORE
 ↓
BLANKING
 ↓
COMP ENABLE
 ↓
ZC WAIT
```

blanking timeは設定可能にする。将来的に`sector duration × ratio`によるadaptive blankingを導入できる構造にする。

### ZC validation

COMP edgeを無条件で採用せず、以下を確認する。

- 正しいfloating phase
- 正しいedge polarity
- blanking後である
- sector内の妥当な時間範囲である
- 前回periodから極端に逸脱していない

異常edgeはrejectし、以下を保持する。

- `valid_zc_count`
- `rejected_zc_count`
- `early_zc_count`
- `late_zc_count`

### Sensorless lock判定

1回のZCだけでclosed-loopへ移行しない。6～12 sector程度の連続した正常ZCを要求し、predicted ZCとactual ZCのphase errorが規定範囲内であることも確認する。回数と閾値は設定値にする。

---

## 12. Commutation scheduling

ZCを検出した瞬間にはcommutationしない。

理想的なZCは60°sectorの中央に発生する。

```text
commutation
   ↓ 30°
zero cross
   ↓ 30°
next commutation
```

連続するZC間隔を`T60`とすると、advance = 0°では以下とする。

```text
next_commutation_time = zc_timestamp + T60 / 2
```

### Dedicated timing timer

delay loopは禁止する。TIM2等のfree-running timerを使用する。

```text
COMP edge
 ↓
timestamp取得
 ↓
T60計算
 ↓
next commutation timestamp計算
 ↓
TIM compare設定
 ↓
timer compare event
 ↓
TIM1 COM event
```

commutation timing jitterをCPU loadから可能な限り分離する。

### Period filtering

瞬間ノイズでcommutation periodを急変させない。軽量IIRを使用可能とする。

```text
filtered_T60 = old × 3/4 + new × 1/4
```

filter coefficientは設定値とし、過度なfilterで加速追従性を落とさない。

### Advance timing

最初はadvance = 0°で成立させる。完全に安定した後、必要な場合のみ5°、10°、15°等を評価する。

```text
Tdelay = T60 × (30° - advance) / 60°
```

advanceを初期実装の必須条件にしない。

---

## 13. Loss of synchronization

closed-loop中にZCを失った場合、そのまま無限にcommutationを継続しない。

検出項目：

- ZC timeout
- impossible period
- too many rejected ZC
- RPM jump

初期実装では次を基本とする。

```text
PWM OFF
 ↓
短時間待機
 ↓
restart
```

無理な即時再同期より、安全停止と再始動を優先する。

---

## 14. Duty controlと電流制約

最初はdirect duty controlだけを実装する。sensorlessが安定するまでRPM PIを追加しない。startup dutyとRUN dutyは別設定にする。

現PCBではMP6540HAのSOA/SOB/SOC current-sense outputがSTM32へ接続されていることを確認できない。このため、以下は使用不可と考える。

- phase-current control
- FOC current loop
- software current limit

MP6540HAの内部protectionをmotor current regulatorとして扱わない。

### 必須保護

- maximum startup duty
- maximum run duty
- startup timeout
- maximum RPM
- minimum valid RPM
- ZC timeout
- desync detection
- restart limit

異常時は`TIM1 MOE = OFF`等を利用し、hardware outputを即座に停止する。

---

## 15. Debug instrumentation

「なんとなく回らない」状態を避け、原因を観測できるようにする。

保持する情報：

```text
motor_state
sector
duty
commutation_timestamp
zc_timestamp
raw_T60
filtered_T60
predicted_zc
actual_zc
phase_error
valid_zc_count
rejected_zc_count
lost_zc_count
startup_count
startup_failure_count
fault_reason
```

### GPIO debug output

オシロスコープ / logic analyzerで確認できるdebug GPIOを用意する。

- DEBUG1 = commutation event
- DEBUG2 = valid ZC event
- DEBUG3 = expected ZC window（可能なら）

高速ISR内の`printf`よりdebug GPIOを優先する。

### Debug event buffer

高速イベントはring bufferへ保存し、main loopからUART等へ出力する。

```c
typedef struct {
    uint32_t timestamp;
    uint8_t event;
    uint8_t sector;
    uint32_t value;
} MotorDebugEvent;
```

ISRはeventを書くだけにする。

---

## 16. DShot

DShotはmotor control完成後に追加する。最初からDShotとBLDC制御を同時にデバッグしない。

```text
固定duty
 ↓
sensorless完成
 ↓
UART等でduty変更
 ↓
DShot追加
```

DShot decoderはmotor controlから完全に分離する。

```text
DShot → motor_command → motor controller
```

最終的にはPA2を外部command入力として使う可能性がある。PA2上の`PWM1`信号の用途を、既存コードと回路で確認すること。

DShotはTIM input capture + DMAを第一候補とし、GPIO pollingは禁止する。最初はDShot300で十分とし、DShot600は必要になってから追加する。

---

## 17. Software modules

責務を次の程度に分離する。

```text
motor_hw.c
    TIM1 / COMP / timing timer

motor_commutation.c
    six-step table / sector transition

motor_bemf.c
    COMP mux / edge validation / ZC handling

motor_startup.c
    ALIGN / forced ramp / lock acquisition

motor_timing.c
    T60 / filtering / next commutation scheduling

motor_control.c
    state machine / duty

motor_fault.c
    protection

motor_debug.c
    event trace

dshot.c
    後で追加
```

巨大な`motor.c`一枚にすべて書かない。一方で、汎用ESC frameworkも作らない。

### State machine

最低限、以下を明示的なstateとして持つ。

```c
MOTOR_STOP
MOTOR_ALIGN
MOTOR_FORCED_START
MOTOR_ACQUIRE
MOTOR_SENSORLESS
MOTOR_FAULT
```

状態遷移を暗黙的なflagの組み合わせで実装しない。

---

## 18. Hardware-in-the-loop自律開発ループ

### 18.1 前提

開発中はデバッガーと実機を接続したままにする。Claude Codeは、承認済みMilestoneの範囲内で次の操作を自律的に実行してよい。

- debugger probeとtarget MCUの接続確認
- build
- firmware flash
- target reset / run / halt
- debugger経由のregister、memory、fault stateの取得
- UART、SWO、debug event buffer等のログ取得
- test commandの実行
- 取得結果の解析
- 1つの原因仮説に対応する最小変更
- 再build、再flash、再試験

接続中であることだけを根拠に、未確認のdebugger種類、書込みコマンド、serial port、電源制御方法を決め打ちしない。リポジトリ、設定ファイル、接続デバイスから実環境を特定すること。

### 18.2 基本ループ

承認済みMilestone内では、次のループをユーザーの逐次承認なしで回す。

```text
現在状態を保存
 ↓
仮説を1つ立てる
 ↓
その仮説を判定できる観測方法を決める
 ↓
必要なら最小限のコード変更
 ↓
build
 ↓
flash
 ↓
安全な初期条件で実行
 ↓
ログ / debugger / debug GPIO結果を取得
 ↓
期待値と実測値を比較
 ↓
結果と次の仮説を記録
 ↓
同じMilestone内で次ループ
```

1ループでは原則として**制御ロジック1点またはパラメータ1点だけ**を変更する。複数変更が不可避な場合は、変更同士を分離できない理由を記録する。

### 18.3 自律実行の境界

同一Milestone内の以下は自律実行してよい。

- instrumentationの追加・調整
- bug fix
- parameter sweep
- build / flash / resetの反復
- 短時間の低duty試験
- 同じ成功条件に対する再現試験
- fault発生後の原因調査と、安全な条件での再試験

次の場合は作業を止め、結果を報告して承認を待つ。

- 次のMilestoneへ進むとき
- 回路図とMCU peripheral mappingに矛盾がある
- PCB変更、配線変更、部品交換が必要
- 電流、温度、回転数等の安全上限を引き上げる必要がある
- protectionを無効化しなければ進めない
- flash / debugger接続が不安定で、誤書込みの可能性がある
- 観測手段がなく、推測で進めるしかない
- 同じ失敗が続き、追加試験が新しい情報を生まない

### 18.4 通電・回転試験の安全規則

実機が接続されていても、いきなりmotor outputを有効化しない。

各作業開始時に以下を確認する。

- target MCUとprobeが正しく認識されている
- firmware imageと対象MCUが一致している
- motor停止状態から開始する
- duty commandの初期値が0である
- maximum duty、timeout、ZC-loss、desync protectionが有効である
- emergency stopとしてTIM1 MOEを即時clearできる
- watchdogまたは同等の停止経路が機能する
- 既知の安全な電源電圧である

初回試験または制御方式変更後は、以下を守る。

1. motor未接続でPWM波形・Hi-Z・dead-timeを確認する
2. 接続後はminimum practical dutyから始める
3. 1回のenergize時間を短く制限する
4. 正常な転流またはZCが確認できてから段階的にdutyを上げる
5. duty、試験時間、回転数上限を一度に引き上げない

次を検出した場合は直ちにPWMを停止し、同条件で自動再始動しない。

- HardFault、assert、watchdog reset
- debuggerまたはtargetとの通信断
- ZC timeout / desync
- impossible period / RPM jump
- gate stateまたはsector stateの不整合
- commandなしでのmotor energize
- 設定したmaximum RPM、duty、連続運転時間の超過
- 利用可能な計測系が示す過電流、低電圧、過熱
- ユーザーによる停止要求

異音、振動、発熱、臭いなど、Claude Codeから直接観測できない項目を「正常」と推定してはならない。それらの確認が必要な段階では、短時間試験後にユーザーへ確認を求める。

### 18.5 進捗停滞時の停止条件

無限ループは禁止する。以下のいずれかで一度停止し、調査結果を報告する。

- 同一failure signatureが3回連続した
- 10回の実機ループでMilestoneの測定値が改善しない
- 2つ以上の仮説が観測不能で区別できない
- build / flash / resetのいずれかが3回連続で失敗した
- hardware faultの可能性がsoftware faultより高くなった

停止時には、単に「失敗した」と報告せず、以下をまとめる。

- 最後に正常だった状態
- failure signature
- 試した仮説と各結果
- 変更したcommit / diff
- 取得ログの場所
- 最も可能性の高い原因
- 次に必要な観測またはユーザー操作

### 18.6 記録と再現性

各ループについて最低限、以下を機械可読なログまたはMarkdownへ追記する。

```text
trial_id
timestamp
git_commit / working tree diff
firmware build identifier
milestone
hypothesis
single_change
build result
flash result
test conditions
duty / voltage / timeout
observed result
fault reason
decision
next action
```

ビルド成果物とログを混同しない。実機へ書き込んだbinaryを特定できるよう、可能ならfirmware build identifierまたはGit SHAを埋め込む。

### 18.7 Milestone完了報告

Milestoneの成功条件を満たしたら自動的に次へ進まず、次を簡潔に報告して承認を待つ。

- 実装した内容
- 実測結果
- 成功条件との対応
- 残存リスク
- 次Milestoneで最初に行う試験

---

## 19. Implementation milestones

### Milestone 0：既存プロジェクト調査

**コード変更禁止。** 以下を調査して報告する。

- TIM1設定
- AF mapping
- COMP mapping
- ADC mapping
- clock tree
- PWM frequency
- existing motor code

### Milestone 1：TIM1出力

TIM1だけ実装する。モーターを接続せず、CH1/1N、CH2/2N、CH3/3Nの波形をオシロで確認する。

確認項目：

- PWM
- dead-time
- Hi-Z
- sector transition

### Milestone 2：Open-loop forced six-step

固定dutyのopen-loop forced six-stepだけを実装する。BEMFは制御に使わない。低dutyから始め、確実に始動・加速することを確認する。

### Milestone 3：COMP観測

forced six-step中にCOMPを有効化するが、まだ制御には使用しない。

記録：

- ZC timestamp
- expected edge
- actual edge

オシロでphase voltage、BEMF_N、ZC debug pinを比較する。

### Milestone 4：ZC validation

まだZCからcommutationしない。全6 sectorでZCが正しい順番・極性で検出できることを確認する。

### Milestone 5：Sensorless closed-loop

```text
ZC → T60/2 → scheduled commutation
```

を実装し、低～中速で安定させる。

### Milestone 6：Startup → sensorless handover

複数回のvalid ZCを確認後に切り替える。100回以上の連続起動試験を行う。

### Milestone 7：高速化

50k → 70k → 90k → 100k rpmのように段階的に確認する。突然100% dutyへしない。

### Milestone 8：Advance timing

必要な場合のみ追加する。

### Milestone 9：DShot

motor control完成後に追加する。

---

## 20. 最初に提出する内容

この指示書を受け取った直後にはコードを書かない。リポジトリ全体を調査し、次を提示する。

### A. Hardware mapping

以下についてGPIO、AF、timer channel、COMP channel、ADC channelを一覧化する。

```text
HSA / LSA
HSB / LSB
HSC / LSC
BEMF_A / BEMF_B / BEMF_C / BEMF_N
PWM1
```

### B. Timer design

TIM1、timing timer、COMPをどう接続するか提案する。

### C. Current code

現在すでに実装されている内容を整理する。

### D. Difference

既存コードと本設計との差分を整理する。

### E. Milestone 1 implementation plan

最初に変更するファイルと確認方法を提示する。

**ここまで提示して承認を待つこと。承認前にコードを変更しないこと。**

---

## 21. 禁止事項

- FOCへの変更
- SimpleFOC導入
- AM32移植
- ESCape32移植
- sensorless observer追加
- 高度な状態推定器追加
- DShotを最初に実装
- telemetryを最初に実装
- bidirectional motor対応
- 汎用ESC化
- 大量のHAL interrupt処理
- PWM ISRによるZC polling
- ADC busy polling
- delay loopによるcommutation
- ISR内`printf`
- 動作中コードの無関係なrewrite

問題発生時は次の順序を守る。

```text
原因仮説
 ↓
観測方法
 ↓
1つだけ変更
 ↓
再測定
```

複数のパラメータを同時に変更しない。

---

## 22. 最終成功条件

- 100回連続startupで重大な失敗なし
- sensorless handover成功
- 100,000 rpm級で連続運転
- ZC dropout時に安全停止
- desync時にMOSFETを安全停止
- RPM変化時に同期を維持

オシロスコープで以下が理論どおりであることも確認する。

- phase voltage
- virtual neutral
- zero crossing
- commutation timing

---

## 23. 実装順序の要約

```text
TIM1が正しく6出力を生成
 ↓
open-loop 6-stepで回転
 ↓
BEMFを観測するだけ
 ↓
6 sectorすべてでZC確認
 ↓
ZCから30°後をtimer予約
 ↓
sensorless化
 ↓
handover
 ↓
高速化
 ↓
DShot
```

この順序を崩さず、各段階で「どこまで正しく動いているか」を観測可能にすること。
