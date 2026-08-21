#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_gen_classics_batch.py —— 用 DeepSeek 生成首批经典章节原文, 写入 content/classics/<slug>/chapters/。

背景: 当前网络下维基文库/ctext 等公版源不可达, 用 LLM 生成初始原文并标注「待核查」
(credibility_level: B / text_source 注明 AI 生成)。公版恢复后应以校勘本替换(质量分级 S/A)。
用法: python content/tools/_gen_classics_batch.py [--slug daxue] [--slug zhongyong] ...
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

CONTENT_ROOT = pathlib.Path(__file__).resolve().parent.parent
KEY = re.search(r"DEEPSEEK_API_KEY=(sk-[0-9a-f]+)", (CONTENT_ROOT.parent / "backend" / ".env").read_text(encoding="utf-8")).group(1)
# 非推理模型: deepseek-chat(deepseek-v4-flash 是推理模型, reasoning_tokens 会吃掉 max_tokens 预算)
MODEL = "deepseek-chat"


def call(prompt: str, max_tokens: int = 8000) -> str:
    for attempt in range(4):
        budget = max_tokens * (2 ** attempt)
        data = json.dumps(
            {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": budget}
        )
        try:
            r = subprocess.run(
                ["curl", "-sS", "-X", "POST", "https://api.deepseek.com/v1/chat/completions",
                 "-H", f"Authorization: Bearer {KEY}", "-H", "Content-Type: application/json", "-d", data],
                capture_output=True, text=True, timeout=300,
            )
            j = json.loads(r.stdout)
            c = j["choices"][0]["message"]["content"].strip()
            if c:
                return c
            print(f"  [空内容 retry {attempt} budget={budget}] {r.stdout[:120]}", file=sys.stderr)
        except Exception as e:
            print(f"  [异常 retry {attempt}] {e}", file=sys.stderr)
        time.sleep(4)
    return ""


# 每部经典: slug / 标题 / 章节清单 (chapter_number, chapter_title, 生成提示要点)
CLASSICS = {
    "daxue": {
        "title": "大学",
        "chapters": [
            (1, "大学", "经一章 + 传十章(三纲领八条目, 格物致知诚意正心修身齐家治国平天下)"),
        ],
    },
    "zhongyong": {
        "title": "中庸",
        "chapters": [
            (1, "中庸", "全篇(首章天命之谓性至末章, 含君子中庸/诚者自成等核心段落)"),
        ],
    },
    "sunzibingfa": {
        "title": "孙子兵法",
        "chapters": [
            (1, "始计第一", "始计: 五事七计, 兵者国之大事"),
            (2, "作战第二", "作战: 兵贵胜不贵久, 因粮于敌"),
            (3, "谋攻第三", "谋攻: 不战而屈人之兵, 知己知彼百战不殆"),
            (4, "军形第四", "军形: 先为不可胜, 胜兵先胜而后求战"),
            (5, "兵势第五", "兵势: 以正合以奇胜, 势如扩弩节如发机"),
            (6, "虚实第六", "虚实: 避实击虚, 因敌制胜"),
            (7, "军争第七", "军争: 以迂为直以患为利, 避其锐气击其惰归"),
            (8, "九变第八", "九变: 智者之虑必杂于利害"),
            (9, "行军第九", "行军: 处军相敌, 令之以文齐之以武"),
            (10, "地形第十", "地形: 地形有六, 知彼知己胜乃不殆"),
            (11, "九地第十一", "九地: 散地轻地争地交地衢地重地圮地围地死地"),
            (12, "火攻第十二", "火攻: 以火佐攻者明, 主不可以怒而兴师"),
            (13, "用间第十三", "用间: 五间俱起, 先知者不可取于鬼神"),
        ],
    },
    "mengzi": {
        "title": "孟子",
        "chapters": [
            (1, "梁惠王上", "梁惠王上: 王何必曰利, 五十步笑百步, 仁者无敌"),
            (2, "梁惠王下", "梁惠王下: 乐民之乐者民亦乐其乐, 与民同乐"),
            (3, "公孙丑上", "公孙丑上: 我善养吾浩然之气, 四端说"),
            (4, "公孙丑下", "公孙丑下: 天时不如地利地利不如人和, 得道多助"),
            (5, "滕文公上", "滕文公上: 民之为道也有恒产者有恒心, 劳心者治人"),
            (6, "滕文公下", "滕文公下: 富贵不能淫贫贱不能移威武不能屈, 大丈夫"),
            (7, "离娄上", "离娄上: 徒善不足以为政徒法不能以自行, 诚者天之道"),
            (8, "离娄下", "离娄下: 君子之泽五世而斩, 以其昏昏使人昭昭"),
            (9, "万章上", "万章上: 天不言以行与事示之而已, 禅让与世袭之辨"),
            (10, "万章下", "万章下: 伯夷圣之清者也, 集大成者金声玉振"),
            (11, "告子上", "告子上: 人性之善也犹水之就下, 舍生取义"),
            (12, "告子下", "告子下: 生于忧患而死于安乐, 天将降大任于是人也"),
            (13, "尽心上", "尽心上: 尽其心者知其性也, 万物皆备于我, 穷则独善其身"),
            (14, "尽心下", "尽心下: 民为贵社稷次之君为轻, 春秋无义战"),
        ],
    },
    "zhuangzi": {
        "title": "庄子",
        "chapters": [
            (1, "逍遥游第一", "内篇·逍遥游: 鲲鹏之喻, 无待逍遥, 至人无己神人无功圣人无名"),
            (2, "齐物论第二", "内篇·齐物论: 吾丧我, 天籁地籁人籁, 是非之辩, 庄周梦蝶"),
            (3, "养生主第三", "内篇·养生主: 缘督以为经, 庖丁解牛, 安时而处顺"),
            (4, "人间世第四", "内篇·人间世: 颜回见仲尼, 心斋, 无用之用, 栎社树"),
            (5, "德充符第五", "内篇·德充符: 王骀兀者, 德有所长而形有所忘, 无情之说"),
            (6, "大宗师第六", "内篇·大宗师: 知天之所为, 真人, 相忘于江湖, 坐忘"),
            (7, "应帝王第七", "内篇·应帝王: 明王之治, 壶子四示, 浑沌之死"),
            (8, "骈拇第八", "外篇·骈拇: 骈拇枝指, 仁义非道德之正"),
            (9, "马蹄第九", "外篇·马蹄: 马蹄践霜雪, 伯乐治马, 至德之世"),
            (10, "胠箧第十", "外篇·胠箧: 胠箧探囊, 圣人生而大盗起, 窃钩者诛窃国者侯"),
            (11, "在宥第十一", "外篇·在宥: 闻在宥天下, 黄帝问广成子, 无为而治"),
            (12, "天地第十二", "外篇·天地: 天地有大美而不言, 玄珠之喻, 抱瓮灌畦"),
            (13, "天道第十三", "外篇·天道: 天道运而无所积, 圣人之心静, 轮扁斫轮"),
            (14, "天运第十四", "外篇·天运: 天其运乎, 孔子见老聃, 六经先王之陈迹"),
            (15, "刻意第十五", "外篇·刻意: 刻意尚行, 恬淡寂漠, 养神之道"),
            (16, "缮性第十六", "外篇·缮性: 缮性于俗, 古之治道者, 知与恬交相养"),
            (17, "秋水第十七", "外篇·秋水: 秋水时至, 河伯望洋, 井蛙不可语于海, 庄子钓于濮水"),
            (18, "至乐第十八", "外篇·至乐: 天下有至乐无有哉, 鼓盆而歌, 髑髅之见"),
            (19, "达生第十九", "外篇·达生: 达生之情者, 佝偻承蜩, 醉者坠车, 梓庆削木为鐻"),
            (20, "山木第二十", "外篇·山木: 庄子行于山中, 材与不材之间, 螳螂捕蝉"),
            (21, "田子方第二十一", "外篇·田子方: 田子方侍坐, 哀莫大于心死, 真画者解衣般礴"),
            (22, "知北游第二十二", "外篇·知北游: 知北游于玄水之上, 天地有大美, 道不可闻"),
            (23, "庚桑楚第二十三", "杂篇·庚桑楚: 庚桑楚居畏垒之山, 卫生之经, 宇泰定者发乎天光"),
            (24, "徐无鬼第二十四", "杂篇·徐无鬼: 徐无鬼见武侯, 郢人运斤, 狗不以善吠为良"),
            (25, "则阳第二十五", "杂篇·则阳: 则阳游于楚, 蘧伯玉行年六十而六十化, 蜗角之争"),
            (26, "外物第二十六", "杂篇·外物: 外物不可必, 涸辙之鲋, 得鱼忘筌, 无用之用"),
            (27, "寓言第二十七", "杂篇·寓言: 寓言十九重言十七, 万物皆种也"),
            (28, "让王第二十八", "杂篇·让王: 尧让天下于许由, 越人三世弑其君, 曾子居卫"),
            (29, "盗跖第二十九", "杂篇·盗跖: 盗跖与孔子之辩, 天与地无穷人死者有时"),
            (30, "说剑第三十", "杂篇·说剑: 天子之剑诸侯之剑庶人之剑"),
            (31, "渔父第三十一", "杂篇·渔父: 渔父见孔子, 真者精诚之至, 礼者世俗之所为"),
            (32, "列御寇第三十二", "杂篇·列御寇: 列御寇之齐, 庄子将死, 在上为乌鸢在下为蝼蚁"),
            (33, "天下第三十三", "杂篇·天下: 天下之治方术者, 道术将为天下裂, 百家之评"),
        ],
    },
    "hanfeizi": {
        "title": "韩非子",
        "chapters": [
            (1, "主道", "主道: 道者万物之始, 虚静无为, 明君之道"),
            (2, "有度", "有度: 国无常强无常弱, 奉法者强则国强, 法不阿贵"),
            (3, "二柄", "二柄: 明主之所导制其臣者, 刑德二柄"),
            (4, "孤愤", "孤愤: 智术之士明察, 处势卑贱, 法术之士与当途之人"),
            (5, "说难", "说难: 凡说之难, 在知所说之心, 逆鳞之说"),
            (6, "喻老", "喻老: 有形之类大必起于小, 千丈之堤以蝼蚁之穴溃"),
            (7, "五蠹", "五蠹: 上古竞于道德中世逐于智谋当今争于气力, 儒以文乱法侠以武犯禁"),
            (8, "显学", "显学: 世之显学儒墨也, 无参验而必之者愚也"),
            (9, "定法", "定法: 术者因任而授官, 法者宪令著于官府, 法术不可一无"),
            (10, "难势", "难势: 贤人而诎于不肖者则权轻位卑, 势者胜众之资"),
            (11, "问辩", "问辩: 上不明则辩生焉, 明主之国无书简之文以法为教"),
            (12, "内储说上七术", "内储说上: 七术, 众端参观, 必罚明威, 信赏尽能"),
            (13, "外储说左上", "外储说左上: 明主之道, 有术而御之, 楚王卖珠"),
            (14, "难一", "难一: 晋文公将与楚人战, 历山之农者侵畔"),
            (15, "难二", "难二: 景公过晏子, 齐桓公之时, 晏子之为人"),
        ],
    },
    "chuanxilu": {
        "title": "传习录",
        "chapters": [
            (1, "上卷·徐爱录", "徐爱录: 知行合一, 心即理, 格物致知之意"),
            (2, "上卷·陆澄录", "陆澄录: 主一之功, 静时亦觉意思好, 省察克治"),
            (3, "上卷·薛侃录", "薛侃录: 去花间草, 为善去恶是格物, 心外无物"),
            (4, "中卷·答顾东桥书", "答顾东桥书: 知行合一之辩, 真知即所以为行"),
            (5, "中卷·答罗整庵少宰书", "答罗整庵少宰书: 心即理之辩, 求理于吾心"),
            (6, "中卷·答聂文蔚", "答聂文蔚: 良知之教, 天地万物一体之仁"),
            (7, "下卷·黄直录等", "下卷: 四句教, 无善无恶心之体, 致良知, 此心光明"),
        ],
    },
    "liezi": {
        "title": "列子",
        "chapters": [
            (1, "天瑞第一", "天瑞: 子列子居郑圃, 太易太初太始太素, 杞人忧天"),
            (2, "黄帝第二", "黄帝: 黄帝即位, 列子御风, 海上之人有好沤鸟者, 仲尼见痀偻承蜩"),
            (3, "周穆王第三", "周穆王: 穆王不恤国事, 西极之国有化人, 郑人得鹿"),
            (4, "仲尼第四", "仲尼: 仲尼闲居, 用心若镜, 不将不迎"),
            (5, "汤问第五", "汤问: 殷汤问于夏革, 愚公移山, 夸父逐日, 两小儿辩日"),
            (6, "力命第六", "力命: 力谓命曰, 生生死死非物非我, 北宫子与西门子"),
            (7, "杨朱第七", "杨朱: 杨朱游于鲁, 太古之人知生之暂来, 人不婚宦情欲失半"),
            (8, "说符第八", "说符: 列子学射, 持后而处先, 歧路亡羊, 兰子七剑"),
        ],
    },
}


def parse_chapters(text: str) -> dict:
    parts = re.split(r"【(\d+)】", text)
    chaps = {}
    for i in range(1, len(parts), 2):
        num = int(parts[i])
        body = parts[i + 1].strip()
        chaps[num] = body
    return chaps


def gen_classic(slug: str, cfg: dict) -> int:
    out_dir = CONTENT_ROOT / "classics" / slug / "chapters"
    out_dir.mkdir(parents=True, exist_ok=True)
    title = cfg["title"]
    chapters = cfg["chapters"]
    print(f"=== 生成《{title}》({len(chapters)} 章) ===")

    # 第一步: 一次性整书生成(覆盖率优先)
    items = "；".join(f"第{n}章({chap_title})" for n, chap_title, _ in chapters)
    text = call(
        f"输出《{title}》全文, 共 {len(chapters)} 个章节: {items}。"
        "严格格式: 每章以【N】开头(N 为 1 到 {count} 的阿拉伯数字), 后接该章完整原文; 章节之间用空行分隔。"
        "只输出各章原文, 不要任何解释、标题或额外说明。".replace("{count}", str(len(chapters))),
        max_tokens=12000,
    )
    chaps = parse_chapters(text)
    print(f"  整书生成解析到 {len(chaps)} 章")

    # 第二步: 逐章补缺
    for n, chap_title, hint in chapters:
        if n not in chaps or len(chaps[n]) < 20:
            print(f"  补生成第 {n} 章({chap_title}) ...")
            t = call(
                f"输出《{title}》第{n}章「{chap_title}」的完整原文。{hint}。"
                f"以【{n}】开头, 只输出该章原文, 不要解释。",
                max_tokens=4000,
            )
            m = re.search(rf"【\d+】\s*(.*)", t, re.S)
            chaps[n] = (m.group(1).strip() if m else t.strip())

    written = 0
    for n, chap_title, hint in chapters:
        body = chaps.get(n, "").strip()
        if not body or len(body) < 20:
            print(f"  第 {n} 章为空/过短, 跳过")
            continue
        front = (
            "---\n"
            f"classic: {slug}\n"
            f"chapter_number: {n}\n"
            f"chapter_title: {chap_title}\n"
            "review_status: PUBLISHED\n"
            "credibility_level: B\n"
            "contributors:\n"
            "  - id: yiwangxi-team\n"
            "    roles: [transcribe]\n"
            f"    date: {time.strftime('%Y-%m-%d')}\n"
            f"text_source: AI 生成({MODEL}), 待与公版校勘核查\n"
            "---\n\n"
            "## 原文\n\n"
            f"【{n}】{body}\n"
        )
        fname = f"{n:03d}.md" if slug in ("daxue", "zhongyong") else f"{n:03d}.md"
        (out_dir / fname).write_text(front, encoding="utf-8")
        written += 1
        print(f"  OK 第{n}章《{chap_title}》({len(body)} 字)")
    print(f"完成《{title}》: 写入 {written} 章 -> content/classics/{slug}/chapters/")
    return written


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", action="append", help="指定生成哪部经典(可多次), 默认全部")
    args = parser.parse_args()
    slugs = args.slug or list(CLASSICS.keys())
    total = 0
    for slug in slugs:
        if slug not in CLASSICS:
            print(f"未知 slug: {slug}", file=sys.stderr)
            continue
        total += gen_classic(slug, CLASSICS[slug])
    print(f"全部完成: 共写入 {total} 章")


if __name__ == "__main__":
    main()
