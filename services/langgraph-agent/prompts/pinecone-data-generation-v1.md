# Pinecone Data Generation Prompt — v1

Run 10 times (100 records each). Replace `[BATCH]` and `[START]` per run.

---

## PROMPT

Generate **100 Israeli real estate transaction records** as a raw JSON array. No markdown, no explanation.

Each object must have exactly these fields:

| Field | Type | Rules |
|---|---|---|
| `id` | string | `"comp-[START]"` to `"comp-[START+99]"`, zero-padded to 5 digits |
| `property_type` | string | `apartment`(55%) `villa`(10%) `penthouse`(8%) `duplex`(5%) `studio`(5%) `office`(8%) `retail`(5%) `commercial`(4%) |
| `city` | string | Tel Aviv(22%) Jerusalem(14%) Haifa(10%) Herzliya(7%) Ra'anana(5%) Netanya(7%) Beer Sheva(5%) Ramat Gan(8%) Ashdod(5%) Petah Tikva(5%) Rishon LeZion(5%) Modi'in(4%) Kfar Saba(2%) Givatayim(1%) |
| `neighborhood` | string | Real neighbourhood within the city |
| `location` | string | `"{neighborhood}, {city}"` |
| `size_sqm` | float | studio 28–45 · apartment 45–160 · duplex 100–200 · penthouse 120–300 · villa 180–550 · commercial types 30–500 |
| `num_rooms` | int | studio 1 · apartment 2–5 · duplex 4–7 · penthouse 4–8 · villa 5–10 · office/retail/commercial 0 |
| `floor_number` | int | 0–15 for apartments; top floor (8–20) for penthouses; 0 for villas |
| `has_parking` | bool | true for 70% · always true for villas and penthouses |
| `has_balcony` | bool | true for 65% · always false for office/retail/commercial |
| `building_year` | int | 1960–2024 · new condition → 2020–2024 · poor condition → 1960–1985 |
| `condition` | string | `new`(10%) `renovated`(25%) `good`(35%) `fair`(20%) `poor`(10%) |
| `price_listed` | int | NIS · base price/sqm by city × type multiplier × condition adjustment (see below) |
| `price_sold` | int | always ≤ `price_listed` · new: −0–2% · renovated: −1–5% · good: −2–7% · fair: −4–10% · poor: −7–18% |
| `price_per_sqm` | int | `round(price_sold / size_sqm)` — compute exactly |
| `days_on_market` | int | new 7–30 · renovated 10–45 · good 14–60 · fair 30–120 · poor 45–180 |
| `sale_date` | string | ISO date between `2023-01-01` and `2025-06-01`, spread evenly |
| `embed_text` | string | exactly `"{property_type}, {num_rooms} rooms, {size_sqm}sqm, {condition}, {neighborhood}, {city}"` |

### Price/sqm by city (NIS, apartment baseline)
Tel Aviv 40K–85K · Jerusalem 25K–55K · Herzliya 28K–65K · Givatayim 28K–45K · Ramat Gan 22K–42K · Ra'anana 20K–35K · Modi'in 16K–26K · Kfar Saba 18K–30K · Netanya 14K–28K · Haifa 12K–28K · Petah Tikva 12K–22K · Rishon LeZion 13K–22K · Ashdod 10K–18K · Beer Sheva 7K–14K

### Type multipliers on price/sqm
penthouse ×1.35 · duplex ×1.05 · apartment ×1.00 · studio ×0.95 · villa ×0.80 · retail ×0.85 · office ×0.75 · commercial ×0.70

### Condition adjustments on price/sqm
new +15% · renovated +8% · good ±0% · fair −8% · poor −18%

### Batch schedule
| Run | `[START]` | `[START+99]` | City focus |
|---|---|---|---|
| 1 | 00001 | 00100 | Tel Aviv, Jerusalem |
| 2 | 00101 | 00200 | Tel Aviv, Jerusalem |
| 3 | 00201 | 00300 | Tel Aviv, Jerusalem |
| 4 | 00301 | 00400 | Herzliya, Ra'anana, Ramat Gan |
| 5 | 00401 | 00500 | Haifa, Ramat Gan, Givatayim |
| 6 | 00501 | 00600 | Netanya, Modi'in, Kfar Saba |
| 7 | 00601 | 00700 | Netanya, Petah Tikva, Rishon LeZion |
| 8 | 00701 | 00800 | Beer Sheva, Ashdod |
| 9 | 00801 | 00900 | Petah Tikva, Rishon LeZion, Ashdod |
| 10 | 00901 | 01000 | All cities, fill distribution gaps |

Now generate batch **[BATCH]**, IDs **comp-[START]** to **comp-[START+99]**. Return only the JSON array.
