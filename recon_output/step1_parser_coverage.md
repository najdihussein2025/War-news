# Step 1e parser coverage

| metric | current DB | aliases simulated |
|---|---:|---:|
| bulletins complete | 48 | 63 |
| bulletins partial | 166 | 151 |
| bulletins residual_only | 7 | 7 |
| **resolved items / all item candidates** | 3721/4815 | 3816/4637 |
| residual entries total, by kind | 1094: {'leftover_token': 481, 'unresolved_place': 231, 'out_of_scope': 332, 'unresolved_header': 19, 'place_under_unresolved_header': 31} | 821 |
| residual entries per bulletin (median, p90) | 3, 11 | — |
| timeline events with exact time | 36 | 36 |

- S4 workload: 110 bulletins have a place-like residual under an approved header.

## Top residual texts by kind

- `leftover_token` / `عيتا`: 37
- `leftover_token` / `الجبل`: 37
- `leftover_token` / `حلتا`: 28
- `unresolved_place` / `عيتا الجبل`: 25
- `leftover_token` / `بسطره`: 23
- `leftover_token` / `مزرعه`: 18
- `unresolved_place` / `مزرعه بسطره عند اطراف كفرشوبا`: 18
- `leftover_token` / `وادي`: 18
- `leftover_token` / `الطيبه`: 16
- `leftover_token` / `الشقيف`: 16
- `unresolved_place` / `حلتا`: 15
- `leftover_token` / `بين`: 13
- `leftover_token` / `سدانه`: 12
- `unresolved_place` / `الطيبه`: 11
- `leftover_token` / `القصير`: 10
- `unresolved_place` / `القصير`: 10
- `leftover_token` / `علمان`: 10
- `leftover_token` / `الشومريه`: 10
- `unresolved_place` / `علمان الشومريه`: 10
- `leftover_token` / `مظلم-بيت`: 9

## Remaining blockers by class

- leftover tokens: 133
- unresolved places: 110
- prose/timeline: 79
- unresolved headers: 15

## Window rules

- explicit_date: 96
- overnight:end_time_ignored: 45
- default: 41
- overnight: 18
- default:end_time_ignored: 13
- explicit_date:stale_suspect: 6
- explicit_date:future_ignored: 1
- broad_partial:end_time_ignored: 1

## Top leftover tokens

- `عيتا`: 41
- `الجبل`: 41
- `حلتا`: 28
- `بسطره`: 23
- `مزرعه`: 18
- `وادي`: 18
- `الطيبه`: 16
- `الشقيف`: 16
- `بين`: 13
- `سدانه`: 12
- `القصير`: 10
- `علمان`: 10
- `الشومريه`: 10
- `مظلم-بيت`: 9
- `ليف`: 9
- `منطقه`: 9
- `صريين`: 8
- `صوتيه`: 8
- `كفرمان`: 8
- `دوحه`: 7
- `شقه`: 6
- `سكنيه`: 6
- `الخردله`: 5
- `الدير-النبطيه`: 5
- `الفوقا`: 5
- `واطراف`: 5
- `دوبيه`: 5
- `حانين`: 5
- `السدانه-كفرشوبا`: 5
- `القنطره-الطيبه`: 5

## Top unresolved places

- `عيتا الجبل`: 25
- `الطيبه`: 11
- `حلتا`: 10
- `القصير`: 10
- `علمان الشومريه`: 10
- `مزرعه بسطره عند اطراف كفرشوبا`: 9
- `وادي مظلم-بيت ليف`: 9
- `صريين`: 8
- `سدانه عند اطراف الهباريه`: 8
- `اطراف عيتا الجبل`: 8
- `مرتفعات حلتا`: 8
- `حرش عيتا الجبل`: 8
- `دوحه كفرمان`: 7
- `مجري نهر الخردله`: 5
- `حي الدير-النبطيه الفوقا`: 5
- `مرتفعات حلتا بقذيفتين`: 5
- `الطيبه لجهه دير سريان`: 5
- `بسطره`: 5
- `حانين`: 5
- `السدانه-كفرشوبا`: 5
- `بين القنطره-الطيبه`: 5
- `سدانه`: 4
- `وادي الخنازير-القصير`: 4
- `عبترون`: 4
- `حي الرويس-النبطيه`: 3
- `الريحان`: 3
- `جبل السويداء-كفررمان`: 3
- `الكفور`: 3
- `عين التينه-البقاع الغربي`: 3
- `سدانه-الهباريه`: 3

## Unresolved headers

- `صفحه الاعلامي الشهيد علي شعيب`: 5
- `قصف مدفعي يستهدف القصير - جنوب لبنان`: 3
- `الغارات من الطيران الحربي التي استهدفت عده مناطق في الجنوب`: 1
- `القصف المدفعي و قد طال المناطق التاليه`: 1
- `عمليات التفجير التي قام بها العدو و قد طالت بلدات`: 1
- `عمليات التمشيط التي قام بها العدو وقد طالت بلدات`: 1
- `باخلاء مبني عند اطراف البلده و قام بعد ذلك بتدميره، اضافه الي غارات اخري استهدفت بلده النبطيه الفوقا`: 1
- `استهدف العدو الاسرائيلي باعمال تفجير وقصف مدفعي اطراف بلده حلتا، تزامنا مع انسحاب قوه معاديه منها`: 1
- `دوحه كفرمان`: 1
- `Summary of israeli attacks on the town of Al-Mansouri so far`: 1
- `نفذ العدو عمليه تمشيط بالاسلحه الرشاشه باتجاه بلده عيتا الجبل`: 1
- `قصف مدفعي معاد استهدف حرش عيتا الجبل`: 1
- `قنابل مضيئه فوق`: 1

## Invariant violations

Checked over 221 bulletins.
- header provenance: 0
- residual header: 0
- secondary != primary: 0
