# 拓展状态与表情

Python 3.10+，先安装 requirements.txt。图集1536×2288，8列11行，每格192×208，透明RGBA。

行0待机6帧，第7格为中性视线；行1/2左右移动各8帧；行3招呼4帧；行4跳跃5帧；行5错误8帧；行6等待6帧；行7工作6帧；行8完成6帧；行9/10为顺时针16方向视线。其余格必须全透明。

打工增强版只替换行5–8。assets/dafeiyu-work 内每张横条1536×208，与 work-edition.json 一起构成可复建素材。拓展时保持角色比例、轮廓、面部身份和帧间对齐，空格保持透明；先预览再安装。请保留署名与使用条件。

```sh
python tools/pet_tool.py build --base pets/dafeiyu-starter --config work-edition.json --output dist/dafeiyu-work
python tools/pet_tool.py validate dist/dafeiyu-work
python tools/pet_tool.py preview dist/dafeiyu-work --output dist/preview.html --compare pets/dafeiyu-starter
```

输出目录必须尚不存在。无损WebP保存必须 exact=True，以保留透明像素的RGB值。验证器检查结构、空格、透明像素残留；美术质量、循环衔接与视线方向仍需人工检查。

目前Codex按既定九种动画状态和16视线读取图集。新增“喝咖啡”等表情可替换现有状态或制作独立主题宠物；额外命名状态不会自动获得运行时触发支持。
