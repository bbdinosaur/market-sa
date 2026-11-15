# MarketSA

RDKit 说这个分子很好合成。销售回信说：这个结构我们做不了。

MarketSA 试图把后者也算进 SA 分数里。丢进去一个 SMILES，它先去公开目录里瞅一眼有没有人在卖，再让你把外包合成公司的真实回复（接不接、多少钱、多久能做）记进本地账本。分数方向跟 RDKit SA 一样：**1 是好做，10 是劝退**。

灵感其实很单纯，也有点开玩笑：分子生成里大家都用计算出来的 SA，但它并不是真实可合成性。那要不要把生成的分子当成合成订单，丢给各家 CRO，看他们愿不愿意接？愿意就当好做，不愿意就当难做，再加上报价和周期，粒度越细越好。Human in the loop，销售也在 loop 里。

请把这个玩笑停在「研究工具」这一步。**本工具不会替你给任何公司发邮件、填询价表、下合成订单。** 它只查公开目录、给你一份自己去发的询价草稿，以及一个把真实回复粘回来的账本。不要写成自动群发器，化学公司的销售也是人。

English: MarketSA is a slightly unserious, market-informed SA score. 1 = easier, 10 = harder, same direction as RDKit SA. It looks at public catalogs and a local quote ledger (accept / decline / price / lead time). It never auto-sends RFQs, and it never invents vendors, prices, or lead times. If all it has is a calculated score, it will say so.

## 安装

Python 3.13+。

```bash
git clone https://github.com/bbdinosaur/market-sa.git
cd market-sa
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

然后可以直接用 `market-sa`，或者 `.venv/bin/python -m market_sa`。

第一次评估时，`molbloom` 可能会下载大约 100 MB 的 `zinc-instock` 过滤器，放到 `data/cache/molbloom/`（也可以用 `MARKET_SA_CACHE_DIR` 改到别处）。打包里已经带了迷你版 `zinc-instock-mini`。完整的 `zinc20` 大约 2 GB，默认不去碰；只有你设了 `MARKET_SA_BLOOM_EXTRA=1`，或本地已经缓存过，才会查。

## 用法

```bash
# 评估一下乙醇
market-sa eval 'CCO'

# 只要 JSON
market-sa eval 'CCO' --json

# 把真实报价记进本地账本（不会外发）
market-sa add-quote --smiles 'CCO' --company 'Example CRO' \
  --decision accepted --price 120 --currency USD \
  --amount 1 --unit g --lead-days 21 --purity 98 --quoted-date 2026-11-15

# 看看这个分子已经记了哪些报价
market-sa quotes --smiles 'CCO'

# 生成中英询价草稿（只写文件 / 打印，不会发送）
market-sa rfq 'CCO'
market-sa rfq 'CCO' --out /tmp/ethanol-rfq.txt

# 本地网页，默认 http://127.0.0.1:8765
market-sa serve
# 或
./scripts/serve.sh
```

`--decision` 可以是 `accepted`、`declined`、`conditional`、`no_response`。拒单时可以再加 `--reason-code chemically_infeasible`（化学上做不了）、`out_of_scope`（不接这类活）、`capacity`（排不过来）或 `other`。

网页上可以贴 SMILES，看结构式、一个大号的 Market SA、证据类型和置信度、对照用的 RDKit SA、供应商表、报价登记表，以及询价草稿的复制和下载。界面是中文的。

## 分数怎么凑出来的

每次都会同时给两个分：

- **RDKit SA**：结构启发式，拿来对照，不是报价。
- **Market SA**：1–10，外加置信度（0–1）和证据类别。

证据由强到弱一共四档，永远用当前最强的一档：

| 类别 | 含义 | 算不算真报价 |
| --- | --- | --- |
| `human_quote` | 你把某家公司的接单 / 拒单 / 有条件回复记进了账本（按 InChIKey 精确对应） | 算，这是最接近最初那个玩笑的信号 |
| `catalog_priced` | 可选的商业目录接口真的返回了价格或货期 | 这是商品目录价，还不是定制合成报价 |
| `catalog_listed` | 出现在 ZINC 可购过滤器或 PubChem 供应商名录里，但没有价格 | 不算 |
| `computational` | 上面都没有，只好回退成 RDKit SA | 当然不算 |

工具不会把「算出来的分」或「名录里出现过」包装成真实报价。

### 你登记的真实报价

拒单会得到高分，也就是更难：

- 化学上不可行 ≈ **9.8**
- 超出业务范围 ≈ **8.7**
- 产能或排期不够 ≈ **8.8**
- 没说原因 ≈ **9.2**

接单则同时看价格和周期。价格先统一折成美元每克（毫克、千克会换算；如果只给了毫摩尔，会用分子量换成克；人民币等货币按 2026-11-15 冻结的近似汇率换算，并在结果里标明，例如 1 元约为 0.1404 美元）。公式长这样：

$$
\text{价格项} = \mathrm{clip}(1 + 1.5\log_{10}(\max(\text{美元/克}, 0.1)), 1, 9)
$$

$$
\text{周期项} = \mathrm{clip}(0.7\log_{2}(\max(\text{货期天数}, 1)/7), 0, 2.5)
$$

两者相加后再限制在 1 到 10。没有货期时，周期项记 0，不会编造天数；接单但缺价格时，基数用 3.5 再加周期项；有条件接单再加 0.8。多条有效记录取中位数，并给出最低、最高和公司名单。无回复是弱信号，记 6.5，而且置信度低；只要同时还存在接单或拒单，无回复就不进入中位数。纯度会存进账本，但还不进入公式。

举个例子：80 元/克、14 天交货，会换成约 11.23 美元/克，Market SA 约为 3.28，证据类别是人工报价。

### 只有供应商名录、没有价格时

分数被限制在 2.5 到 3.5：1 家供应商接近 3.5，100 家以上接近 2.5。具体是按 \(\log_{10}(\text{供应商数}+1)\) 在 1 到 101 家之间插值。供应商越多，置信度也略高；若再被 ZINC 现货过滤器命中，还会再加一点。如果只有过滤器命中、叫不出供应商名字，分数大约 3.2，但置信度会更低，因为过滤器有很小的假阳性。

如果以后接上商业目录接口、真的拿到了标价，就走上面同一套价格–周期公式；标明现货时可以有 −0.5 的「好像比较好买」奖励。

### 什么市场证据都没有

Market SA 就等于 RDKit SA，类别必须写成 `computational`，置信度偏低。界面和命令行都会把这一点写明白。

## 数据从哪来（默认不用 Key）

- **RDKit**：核对 SMILES、规范式、分子量、分子式、InChIKey、二维结构图，以及 Contrib 里的 `SA_Score`。
- **molbloom**：免费的可购性布隆过滤器。`True` 表示**可能**可购（有很小的假阳性），`False` 表示不在该目录。SureChEMBL 是专利文献库，不是商店，会单独标注。
- **PubChem**：用 SMILES 查 CID、属性和 Chemical Vendors 名录。它通常不给价格或货期；没有就是没有，不会编。请求有礼貌限速，并按分子做磁盘缓存。
- **可选商业接口**：只有环境变量存在时才查询，没设置就跳过。支持 `MOLPORT_API_KEY`、`MCULE_API_TOKEN`、`CHEMSPACE_API_KEY`。这些适配器只做检索，不提交询价或订单；密钥不会被打印出来。接口改了或失败了，就记下并忽略，不会伪造价格。
- **本地 SQLite 账本**：默认在 `data/quotes.sqlite`，可用 `MARKET_SA_LEDGER` 改路径。

远端结果缓存在 `data/cache/`，重复评估会很快。PubChem 暂时连不上也没关系，仍会给出 RDKit SA、本地可购性过滤，以及你已经登记过的报价，并作出警告。

## 一些老实话

- 目录里有，不等于现在一定能买到，更不等于定制合成一定接单。
- 没有价格时，别把 Market SA 当成报价。
- 账本好不好用，取决于你粘回来的回复准不准、是不是过期了。
- 生成的询价草稿得你自己发出去。
- 这是研究用的可合成性评估，也可以拿来玩强化学习的奖励设计。它不是自动采购系统，也不是群发销售邮件的理由。

## 开发

```bash
source .venv/bin/activate
pytest
```

`examples/` 里有乙醇、阿司匹林，以及一个不太好买的结构 `ONN1CCCC1` 的评估结果，方便对照。

| 环境变量 | 作用 |
| --- | --- |
| `MARKET_SA_DATA_DIR` | 数据目录，默认是项目下的 `data/` |
| `MARKET_SA_CACHE_DIR` | 缓存目录 |
| `MARKET_SA_LEDGER` | 报价数据库路径 |
| `MARKET_SA_PUBCHEM_INTERVAL` | PubChem 最小请求间隔（秒，默认 0.3） |
| `MARKET_SA_BLOOM_EXTRA` | 设为 `1` 时额外尝试 surechembl / zinc20 |
| `MOLPORT_API_KEY` / `MCULE_API_TOKEN` / `CHEMSPACE_API_KEY` | 可选商业目录 |

## 许可

MIT。RDKit SA Score 来自 Ertl & Schuffenhauer 的开放实现；PubChem 和 molbloom 各有各的使用条款。请尊重供应商网站的访问规范，不要用这个仓库去批量骚扰商家。销售的收件箱不是你的免费 oracle。
