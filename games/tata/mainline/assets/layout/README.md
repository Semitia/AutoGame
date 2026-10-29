# 自动布局识别素材

`clear-arrow.png` 为游戏公共“全部下阵”图标模板。`prepare-controls.png` 是公共元素/开始按钮栏，用于不操作游戏的图像回归测试；两者均不包含昵称、等级、星级或账号标识。原始玩家截图不提交。

地图使用版本化公共资源包中的原图，战场偏移读取当前 StageBattleController.battleFieldRootOffset；不保存旧电脑的屏幕坐标。0.50.1 原 GetBattlePositionByGrid 返回 `(x-.5,y-.5)`，BattleBaseScene.AdjustBackgroundScale 经独立 VM 执行核实：pixelsPerUnit=100 时 scale=(100*1.5/110,100/110,1)。渲染横向压缩由地图图像配准吸收；根偏移和格子统一换到每格 110 原图像素，再由实际画面的仿射矩阵投影。地图和卡片定位均要求图像匹配证据。

识别失败时停在当前界面，不按旧坐标点击；此项仍需实战部署回读验证，不把只读图像核验当成推关成功。
