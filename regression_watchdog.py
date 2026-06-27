#!/usr/bin/env python3
"""
回归测试看门狗 — 每次修改检查器后一键验证
覆盖: 8 个优先级检查器 × 多种边界情况 = 100 条对照用例
用法: python3 regression_watchdog.py
"""
import sys, time
sys.path.insert(0, '.')
from hallucination_detector import FactExtractor, AnchorEngine

TESTS = [
    ("光速是无穷大的", "contradicted", "无穷检测: 光速无限"),
    ("光速不是无穷大的", "unverifiable", "无穷检测: 光速有限 (正例)"),
    ("宇宙是无限的", "unverifiable", "无穷检测: 无知识库事实"),
    ("爱因斯坦发明了原子弹", "contradicted", "否定: 发明原子弹"),
    ("爱因斯坦发明了相对论", "verified", "否定: 发明相对论 (正例)"),
    ("毕昇发明了手机", "unverifiable", "否定: 发明手机 (KB无覆盖)"),
    ("地球不是平的", "verified", "否定: 纠正地平说"),
    ("朱元璋于1378年称帝", "contradicted", "年份: 称帝年错误"),
    ("朱元璋于1368年称帝", "verified", "年份: 称帝年正确"),
    ("明朝于1368年建立", "verified", "年份: 明朝建立年正确"),
    ("明朝于1644年灭亡", "unverifiable", "年份: 灭亡年 (KB无覆盖)"),
    ("秦始皇于公元前221年统一六国", "unverifiable", "年份: 秦朝 (KB无具体年份)"),
    ("珠穆朗玛峰海拔9000米", "unverifiable", "数值: 单数字不对应范围"),
    ("珠穆朗玛峰海拔8848米", "verified", "数值: 高度正确"),
    ("光速每秒40万公里", "unverifiable", "数值: 不匹配范围"),
    ("李白是宋朝诗人", "contradicted", "时序: 李白→宋 (应为唐)"),
    ("苏轼是唐代词人", "contradicted", "时序: 苏轼→唐 (应为宋)"),
    ("毕昇发明了活字印刷术", "verified", "时序: 毕昇→宋→活字印刷 (正确)"),
    ("蔡伦改进了造纸术", "verified", "时序: 蔡伦→汉→造纸 (正确)"),
    ("不对，火锅在汉代已有雏形，远比朱元璋的时代早", "unverifiable", "时序: 纠正句式 (不矛盾)"),
    ("朱元璋发明了宋朝的青花瓷", "contradicted", "时序: 朱元璋→宋 (应为明)"),
    ("康熙是明朝皇帝", "contradicted", "时序: 康熙→明 (应为清)"),
    ("郑和下西洋发生在清朝", "contradicted", "时序: 郑和→清 (应为明)"),
    ("张衡发明了地动仪", "unverifiable", "时序: 张衡→汉→地动仪 (正确)"),
    ("长城在巴黎", "contradicted", "地点: 长城→巴黎"),
    ("故宫在北京", "unverifiable", "地点: 故宫→北京 (正确)"),
    ("兵马俑在西安被发现", "unverifiable", "地点: 兵马俑→西安 (正确)"),
    ("富士山在中国", "unverifiable", "地点: 富士山→中国 (应为日本)"),
    ("金字塔在埃及", "unverifiable", "地点: 金字塔→埃及 (正确)"),
    ("Python由Guido于1991年发布", "verified", "重叠: Python发布年"),
    ("Python是编译型语言", "unverifiable", "重叠: Python编译型 (应为解释型)"),
    ("水在标准大气压下沸点为100度", "verified", "重叠: 水沸点"),
    ("水在标准大气压下沸点为80度", "unverifiable", "重叠: 水沸点错误"),
    ("DNA的双螺旋结构由达尔文提出", "unverifiable", "重叠: DNA发现者错误"),
    ("秦始皇是唐朝的皇帝", "unverifiable", "图谱: 秦始皇→唐 (应为秦)"),
    ("造纸术是蔡伦在东汉发明的", "verified", "图谱: 蔡伦→造纸 (正确)"),
    ("朱元璋发明了火锅", "contradicted", "综合: 朱元璋→火锅"),
    ("地球是平的", "contradicted", "综合: 地平说"),
    ("光速是无限快的", "contradicted", "综合: 光速无限"),
    ("爱迪生发明了手机", "unverifiable", "综合: 爱迪生→手机 (KB无覆盖)"),
    ("林则徐是清朝的禁烟英雄", "unverifiable", "综合: 林则徐→清 (正确)"),
    ("成吉思汗建立了元朝", "unverifiable", "综合: 成吉思汗→元 (正确)"),
    ("忽必烈是宋朝的皇帝", "contradicted", "综合: 忽必烈→宋 (应为元)"),
    ("明代开国皇帝创造了涮肉", "unverifiable", "回归: 发明→涮肉 (不矛盾)"),
    ("朱元璋（1336年－1398年），于1378年在应天称帝", "contradicted", "回归: 生卒年+称帝年错误"),
    ("毕昇发明了活字印刷术", "verified", "回归: 印刷条目多事实共存"),
    ("蔡伦的造纸术是在唐代完善的吗", "unverifiable", "回归: 蔡伦→唐疑问句"),
    ("内阁制度是朱元璋设立的", "contradicted", "回归: 内阁≠朱元璋 (应为永乐)"),
    ("", "unverifiable", "边界: 空字符串"),
    ("对", "unverifiable", "边界: 单字回复"),
    ("不对", "unverifiable", "边界: 单字纠正"),
    ("好", "unverifiable", "边界: 无意义回复"),
    ("2026年", "unverifiable", "边界: 仅年份"),
    ("朱元璋建立了大明朝", "verified", "同义: 大明≈明"),
    ("始皇统一了六国", "verified", "同义: 始皇≈秦始皇→秦"),
    ("大唐的首都是长安", "verified", "同义: 大唐≈唐"),
    ("不是的，火锅汉代就有了", "unverifiable", "纠错: 否定开头+正确事实"),
    ("并非如此，地球不是平的", "unverifiable", "纠错: 并非开头+纠错+事实"),
    ("其实活字印刷术是毕昇在北宋发明的", "verified", "纠错: 其实开头+正确事实"),
    ("岳飞是唐代抗金名将", "contradicted", "扩展: 岳飞→唐 (应为宋)"),
    ("诸葛亮是汉朝军师", "contradicted", "扩展: 诸葛亮→汉 (应为三国)"),
    ("曹操建立了魏国", "verified", "扩展: 曹操→魏 (正确)"),
    ("康熙建立了清朝", "contradicted", "扩展: 康熙建立清 (应为努尔哈赤)"),
    ("乾隆是唐朝的皇帝", "contradicted", "扩展: 乾隆→唐 (应为清)"),
    ("古腾堡发明了印刷术", "unverifiable", "扩展: 古腾堡→铅活字(不是印刷术)"),
    ("火药是中国人发明的", "verified", "扩展: 火药→中国 (正确)"),
    ("指南针是阿拉伯人发明的", "contradicted", "扩展: 指南针→阿拉伯 (应为中国)"),
    ("蔡伦发明了火药", "contradicted", "扩展: 蔡伦→火药 (应为造纸)"),
    ("埃菲尔铁塔在伦敦", "contradicted", "扩展: 铁塔→伦敦 (应为巴黎)"),
    ("泰姬陵在中国", "contradicted", "扩展: 泰姬陵→中国 (应为印度)"),
    ("大本钟在英国伦敦", "verified", "扩展: 大本钟→伦敦 (正确)"),
    ("悉尼歌剧院在美国", "contradicted", "扩展: 歌剧院→美国 (应为澳大利亚)"),
    ("所有人都认为地球是圆的", "unverifiable", "扩展: 绝对化所有人"),
    ("永远不会有比光速更快的东西", "unverifiable", "扩展: 绝对化永远"),
    ("毫无疑问，朱元璋是最伟大的皇帝", "unverifiable", "扩展: 绝对化毫无疑问"),
    ("并不是朱元璋发明了火锅，火锅更早", "unverifiable", "扩展: 并不是开头"),
    ("没有证据表明蔡伦发明了纸", "unverifiable", "扩展: 没有证据开头"),
    ("其实毕昇才是活字印刷的真正发明者", "verified", "扩展: 其实开头正确事实"),
    ("珠穆朗玛峰高9000米", "unverifiable", "扩展: 珠峰高度错误"),
    ("地球到月球的距离是50万公里", "unverifiable", "扩展: 地月距离错误"),
    ("光速是每秒30万公里", "verified", "扩展: 光速正确"),
    ("Python是由Guido van Rossum创建的", "verified", "扩展: Python创建者"),
    ("Java是由微软开发的", "unverifiable", "扩展: Java→微软 (应为Sun)"),
    ("Linux内核由Linus在1991年创建", "verified", "扩展: Linux内核"),
    ("HTTP协议是1995年提出的", "contradicted", "扩展: HTTP→1995 (应为1989)"),
    ("JavaScript和Java是同一种语言", "unverifiable", "扩展: JS=Java (应为不同)"),
    ("……", "unverifiable", "边界: 省略号"),
    ("？？？", "unverifiable", "边界: 问号"),
    ("abcdefg", "unverifiable", "边界: 纯英文无意义"),
    ("苏轼是宋朝的词人", "verified", "补: 苏轼→宋"),
    ("李白是唐代诗人", "verified", "补: 李白→唐"),
    ("杜甫是唐代诗人", "verified", "补: 杜甫→唐"),
    ("岳飞精忠报国", "unverifiable", "补: 岳飞→精忠(无具体事实)"),
    ("忽必烈是元朝开国皇帝", "unverifiable", "补: 忽必烈→元(无具体事实)"),
    ("康熙皇帝是清朝的", "unverifiable", "补: 康熙→清(无具体事实)"),
    ("林则徐虎门销烟发生在清朝", "unverifiable", "补: 林则徐→清(无具体事实)"),
    ("第一次鸦片战争发生在1840年", "unverifiable", "补: 鸦片战争年份(无KB)"),
    ("郑成功收复了台湾", "unverifiable", "补: 郑成功(不在KB)"),
    ("造纸术、印刷术、火药、指南针是四大发明", "verified", "补: 四大发明"),
    ("印刷术是毕昇发明的", "verified", "补: 毕昇→印刷"),
]

engine = AnchorEngine()
extractor = FactExtractor()
t0 = time.time()
passed = 0
failed = 0
false_positives = []
false_negatives = []

for claim, expected, desc in TESTS:
    claims = extractor.extract(claim)
    if not claims:
        verdict = "none"
    else:
        result = engine.verify(claims[0])
        verdict = result.verdict
    if expected == "contradicted":
        ok = (verdict == "contradicted")
        if not ok:
            false_negatives.append((desc, claim, verdict))
    elif expected == "verified":
        ok = (verdict == "verified")
        if not ok:
            false_negatives.append((desc, claim, verdict))
    else:
        ok = (verdict != "contradicted")
        if not ok:
            false_positives.append((desc, claim, verdict))
    if ok:
        passed += 1
    else:
        failed += 1

elapsed = time.time() - t0
print(f"{'='*60}")
print(f"  回归测试看门狗")
print(f"{'='*60}")
print(f"  总用例: {len(TESTS)}")
print(f"  通过:   {passed} ✅")
print(f"  失败:   {failed} ❌")
print(f"  误报:   {len(false_positives)}")
print(f"  漏报:   {len(false_negatives)}")
print(f"  耗时:   {elapsed:.2f}s")
print(f"{'='*60}")
if false_positives:
    print(f"\n🔴 误报:")
    for desc, claim, verdict in false_positives[:5]:
        print(f"  [{desc}] '{claim[:40]}' -> {verdict}")
if false_negatives:
    print(f"\n🟡 漏报:")
    for desc, claim, verdict in false_negatives[:5]:
        print(f"  [{desc}] '{claim[:40]}' -> {verdict}")
if failed == 0:
    print(f"\n✅ 全部通过")
    sys.exit(0)
else:
    print(f"\n❌ {failed} 条失败")
    sys.exit(1)
