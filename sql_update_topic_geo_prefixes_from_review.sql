-- Ręczna korekta geograficznych prefiksów na podstawie eksportu
-- sql_export_topics_with_summaries_for_geo_review.sql.
--
-- Zmieniany jest wyłącznie prefiks [ ... ] w topics.headline_pl;
-- reszta tytułu pozostaje bez zmian. Lista obejmuje tylko wątki z eksportu,
-- które według oceny redakcyjnej miały nieprecyzyjny prefiks.

with prefix_updates(topic_id, prefix) as (
    values
        ('topic_merge_b0f50362cf8dad2be0bbd0c2', '[Ukraina]'),
        ('topic_merge_abac0d623e68a9c0fd9f36df', '[Uganda]'),
        ('topic_merge_65f4dae80a8141264da043a4', '[Wielka Brytania]'),
        ('topic_merge_80c560ca9c39387dc99ff385', '[Hiszpania]'),
        ('topic_merge_f319f770068f5b364da576e4', '[USA]'),
        ('topic_merge_fcb05ece8b0b60979a7d4e34', '[USA]'),
        ('topic_merge_060098fc1a2f3bfe9f9c88db', '[Rosja]'),
        ('topic_merge_308bf03a4ebdd8aa3c34b86a', '[Chiny]'),
        ('topic_merge_3a34ea73a52ae0b37276dd8b', '[Serbia]'),
        ('topic_merge_798d13601155eb889420c293', '[Haiti]'),
        ('topic_merge_beb18a0191926679570dbd89', '[Francja]'),
        ('topic_merge_0e4b16352a31c48a17d3378b', '[Hiszpania]'),
        ('916df8eb8f5293e770361aba', '[Francja]'),
        ('topic_merge_2e3692a43fa249658336c1c2', '[USA]'),
        ('topic_merge_41203786e68df77c407f19c0', '[USA]'),
        ('topic_3d24988e71021b18098923a1', '[USA]'),
        ('topic_merge_a3aaae8a718402aedbf6e93e', '[USA]'),
        ('topic_merge_49b7ff84e4db6f5fc0308119', '[Europa]'),
        ('topic_merge_9b7505c0e7a3e9526438fabe', '[Europa]'),
        ('topic_merge_1e9536900b837e516c38f665', '[Europa]'),
        ('topic_merge_2b4558fec22f1ea51adfec89', '[Chiny]'),
        ('topic_merge_2ee5f9da80f2abb773f744f9', '[Chiny]'),
        ('topic_merge_4b1c78969cbd237f271590a2', '[Włochy]'),
        ('topic_merge_d16a92de95be1ecdd9227cea', '[Francja]'),
        ('topic_merge_2d17cdb273a953f17a4b635b', '[Europa]'),
        ('topic_merge_964ab2be037431833b091326', '[Europa]'),
        ('topic_d84acbe3d41e288708f35609', '[Demokratyczna Republika Konga]'),
        ('topic_543651e950cedf6d2f7a7cf2', '[USA]'),
        ('topic_merge_ec0fd008e1f82574be82de87', '[Polska]'),
        ('topic_5022502d6aec9426b25746a5', '[Europa]'),
        ('topic_merge_9a0764227d56ad514c4dce37', '[Tajlandia]'),
        ('topic_faf6b5342eb73a32628d9ad4', '[USA]'),
        ('topic_merge_ac312900c6a28e5edf9a5e0b', '[Francja]'),
        ('topic_merge_15952a742c794910826350d1', '[USA]'),
        ('topic_06aa298de0ed60f64963b592', '[Europa]'),
        ('topic_merge_3a3b6144d7c5a4513fda877d', '[Hiszpania]'),
        ('topic_0d80ae4aa93f964051333e95', '[USA]'),
        ('topic_merge_3aa4cab72379d6314bc3c9b4', '[Serbia]'),
        ('topic_9cb2976996dff04748f0e526', '[Świat]'),
        ('topic_8132c65f3d77ee56d1b9f84e', '[Europa]'),
        ('topic_merge_ae3ce967a0b65072c5edd2cd', '[Szwajcaria]'),
        ('topic_3769812689925b61ed08c5b7', '[Włochy]')
),
updated as (
    update public.topics as t
    set
        headline_pl = regexp_replace(t.headline_pl, '^\[[^]]+\]', u.prefix),
        updated_at = now()
    from prefix_updates as u
    where t.topic_id = u.topic_id
      and t.status <> 'MERGED'
      and exists (
          select 1
          from public.topic_summaries ts
          where ts.topic_id = t.topic_id
      )
    returning t.topic_id, t.headline_pl
)
select *
from updated
order by topic_id;
