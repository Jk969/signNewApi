# NewAPI 签到脚本集合

多平台 NewAPI 站点的自动签到脚本，支持青龙面板定时运行。核心特性是基于 OpenCV 的滑动验证码自动识别，覆盖登录和签到两个环节。

## 支持平台

| 脚本 | 平台 | 路径 |
|------|------|------|
| signJianYi.py | 简易AI (jeniya.cn) | `scripts/简易api签到/` |
| xiaohuSign.py | 小胡AI (xiaohumini.site) | `scripts/小胡签到/` |
| signYunwu.py | 云雾AI (yunwu.ai) | `scripts/签到/` |

三个脚本基于同一套代码架构，仅 `API_BASE` 域名不同。

## 功能特性

- 多账号批量签到，支持环境变量和文件两种配置方式
- Cookie 缓存机制，避免重复登录
- 滑动验证码自动识别（登录 + 签到）
- 验证码识别失败自动重试（最多 3 次）
- PushPlus 消息推送执行结果

## 快速开始

### 安装依赖

```bash
pip install requests opencv-python numpy Pillow
```

### 配置账号

在对应脚本目录下创建 `account.txt`，每行一个账号：

```
用户名 密码
用户名###密码###备注
```

### 运行

```bash
python scripts/简易api签到/signJianYi.py
```

### 青龙面板

环境变量 `YUNWU_ACCOUNT` 优先级高于文件，格式同上，多账号用 `&` 或换行分隔。

---

## 验证码识别技术详解

这些站点使用 [go-captcha](https://github.com/wenlng/go-captcha) 的 slide-basic 模式——经典的滑动拼图验证码。服务端返回一张带缺口的背景图和一张滑块小图，用户需将滑块拖到缺口位置。

### 交互流程

整个验证码交互分三步：

```
┌─────────────────────────────────────────────────────────────┐
│  1. GET  /api/go-captcha-data/slide-basic                   │
│     ← { captcha_key, image_base64, thumb_base64,            │
│         tile_x, tile_y, tile_width, tile_height }           │
│                                                             │
│  2. POST /api/go-captcha-check-data/slide-basic             │
│     → multipart: point="x,y", key="captcha_key"             │
│     ← { code:0, token:"uuid" }  (验证通过)                  │
│                                                             │
│  3. POST /api/user/login  或  /api/user/checkin             │
│     → { ..., captcha_token: token }                         │
└─────────────────────────────────────────────────────────────┘
```

- **image_base64**: 背景图（带缺口），JPEG 格式
- **thumb_base64**: 滑块图，PNG 格式（带 Alpha 透明通道）
- **tile_y / tile_height**: 滑块在背景图上的纵坐标和高度（服务端直接给出，y 方向无需识别）
- **tile_x**: 滑块起始 x 坐标（固定为 5，即滑块初始位置，不是目标位置）
- **需要识别的只有滑块的 x 方向目标坐标**

### 识别算法：Canny 边缘检测 + 模板匹配

核心思想：**不做像素级比对，而是在边缘空间做模板匹配**。边缘图对颜色、亮度的变化鲁棒，匹配精度更高。

整个算法分四个阶段：

#### 阶段一：图片解码

```python
def decode_base64_image(base64_str):
    if ',' in base64_str:
        base64_str = base64_str.split(',')[1]   # 去掉 data:image/...;base64, 前缀
    img_data = base64.b64decode(base64_str)
    pil_image = Image.open(io.BytesIO(img_data))
    return np.array(pil_image)                   # → H×W×C numpy 数组
```

将 base64 字符串解码为 numpy 数组。背景图得到 HxWx3 的 RGB 数组，滑块图得到 HxWx4 的 RGBA 数组（带透明通道）。

#### 阶段二：提取滑块边缘

```python
if len(slider.shape) == 3 and slider.shape[2] == 4:       # RGBA 四通道
    alpha = slider[:, :, 3]                                # 取 Alpha 通道
    _, mask = cv2.threshold(alpha, 127, 255, cv2.THRESH_BINARY)  # 二值化
    slider_edges = cv2.Canny(mask, 100, 200)               # 边缘检测
else:
    slider_gray = cv2.cvtColor(slider, cv2.COLOR_RGB2GRAY) # RGB 转灰度
    slider_edges = cv2.Canny(slider_gray, 100, 200)
```

**为什么用 Alpha 通道而不是直接转灰度？**

滑块图是 RGBA 格式，Alpha 通道天然区分了滑块区域（不透明）和背景（透明）。对 Alpha 做二值化得到掩码，再 Canny 检测，能得到非常干净的滑块轮廓边缘，不受滑块图案颜色干扰。

```
滑块 RGBA 图          Alpha 通道          二值化掩码          Canny 边缘
┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐
│  ██████  │      │  ██████  │      │  ██████  │      │  ┌────┐  │
│ ████████ │  →   │ ████████ │  →   │ ████████ │  →   │  │    │  │
│  ██████  │      │  ██████  │      │  ██████  │      │  └────┘  │
│   透明    │      │   0x00   │      │   0x00   │      │          │
└──────────┘      └──────────┘      └──────────┘      └──────────┘
```

#### 阶段三：提取背景边缘（ROI 裁剪）

```python
bg_gray = cv2.cvtColor(bg, cv2.COLOR_RGB2GRAY)

margin = 20
y_start = max(0, tile_y - margin)
y_end = min(bg.shape[0], tile_y + tile_height + margin)
bg_roi = bg_gray[y_start:y_end, :]                # 纵向裁剪 ROI

bg_edges = cv2.Canny(bg_roi, 100, 200)
```

**为什么做 ROI 裁剪？**

服务端返回了 `tile_y` 和 `tile_height`，告诉我们滑块缺口在背景图的大致纵向位置。据此在背景图上下各扩展 20 像素裁剪出一个水平条带（ROI），只在这个区域内做匹配。

这样做有两个好处：
1. **大幅减少计算量**：背景图通常是 300x150，裁剪后变成约 300x80，模板匹配的计算量减少近一半
2. **避免误匹配**：背景图中可能存在其他与滑块相似的纹理，限定纵向范围后大幅降低误匹配概率

```
原始背景图 (300×150)
┌──────────────────────────────┐
│                              │
│  ┌────────┐ ← 缺口位置       │  tile_y 已知
│  │  缺口  │                  │
│  └────────┘                  │
│                              │
└──────────────────────────────┘
        ↓ ROI 裁剪 (±20px)
┌──────────────────────────────┐
│  ┌────────┐                  │
│  │  缺口  │                  │  只在这条带内匹配
│  └────────┘                  │
└──────────────────────────────┘
```

#### 阶段四：模板匹配

```python
result = cv2.matchTemplate(bg_edges, slider_edges, cv2.TM_CCOEFF_NORMED)
min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

x = max_loc[0]
```

使用 **归一化互相关（Normalized Cross-Correlation）** 在背景边缘图上滑动滑块边缘图，计算每个位置的相似度得分。`TM_CCOEFF_NORMED` 的结果范围是 [-1, 1]，值越大表示匹配度越高。

`cv2.minMaxLoc` 返回结果矩阵中的最大值位置 `max_loc`，其 x 坐标就是滑块应该滑动到的目标位置。

```
背景边缘图 (宽W)         滑块边缘图 (宽w)
┌──────────────────┐    ┌──────┐
│ ┌─────┐          │    │//////│     滑块模板在背景上从左到右滑动
│ │/////│          │ ←  │//////│     每个位置计算相似度得分
│ └─────┘          │    │//////│
│                  │    └──────┘
└──────────────────┘
        ↓
  匹配结果: max_val=0.73, max_loc=(136, 12)
  → 滑块目标 x 坐标 = 136
```

### 提交坐标与容错

识别出 x 坐标后，以 `multipart/form-data` 提交 `point="x,y"` 和 `key="captcha_key"`：

```python
files = {
    'point': (None, f'{x},{y}'),
    'key': (None, captcha_key),
}
resp = self.session.post(verify_url, headers=headers, files=files)
```

服务端有一定的容差范围（通常 ±5 像素），识别结果不需要像素级精确。当识别失败时，脚本会自动重试（登录验证码最多 3 次，签到验证码最多 2 次），每次重新获取新的验证码。

### 为什么不用深度学习？

对于这种固定风格的滑块验证码，传统 CV 方法已经足够：
- **零训练成本**：不需要标注数据和模型训练
- **无运行时依赖**：不需要 GPU 或 PyTorch/TensorFlow
- **速度快**：单次识别 < 50ms
- **准确率可观**：实测约 70-80% 首次通过率，配合重试机制可达 95%+

边缘检测 + 模板匹配的方案，对这类滑块验证码而言，是简洁高效的选择。

---

## 项目结构

```
sign/
├── scripts/
│   ├── 简易api签到/
│   │   ├── signJianYi.py        # 简易AI签到主脚本
│   │   └── account.txt          # 账号配置
│   ├── 小胡签到/
│   │   ├── xiaohuSign.py        # 小胡AI签到主脚本
│   │   └── account.txt
│   ├── 签到/
│   │   ├── signYunwu.py         # 云雾AI签到主脚本
│   │   └── account.txt
│   ├── telegram/
│   │   └── kcSign.py            # Telegram Bot 签到
│   ├── notify.py                # 通知模块
│   └── ql_sample.py             # 青龙面板示例
└── 登录验证码.txt                # 抓包记录
```

## 注意事项

- 本项目仅供学习交流，请遵守各平台使用条款
- 建议将 GitHub 仓库设为 Private，避免账号密码泄露
- Cookie 缓存文件（`.*.json`）包含 session 信息，不应公开分享
