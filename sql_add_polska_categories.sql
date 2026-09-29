-- Dopisuje kategorię POLSKA do tematów, których głównym miejscem,
-- aktorem lub przedmiotem jest Polska.
-- Wymaga wcześniejszego uruchomienia:
-- supabase_migration_topic_category_polska.sql

insert into public.topic_categories (topic_id, category)
select selected.topic_id, 'POLSKA'
from (
    values
        ('topic_merge_d56f61d3f0e804689a174726'), -- Afera w Szpitalu Południowym
        ('topic_merge_d9b1f27717dffed163a224d6'), -- Substancja ropopochodna na polskich plażach
        ('topic_merge_c13e28b4834da9159597e094'), -- Zespół prokuratorów ds. Zondacrypto
        ('topic_merge_e9f8d932cc3c8e48c84deda3'), -- Referendum w Warszawie
        ('topic_merge_5463b71501dbfb2c26d65122'), -- Zabójstwo w Puszczykowie
        ('topic_b667295eb7d5ce87319dab70'),       -- Planowany atak w szkole w Kujawsko-Pomorskiem
        ('topic_cc72c3c67b1f0855f14976de'),       -- Nowa moneta NBP
        ('topic_merge_4e526552e0fe594386a804eb'), -- Afera Zondacrypto
        ('topic_merge_3e7176cd72289b117369b9a1'), -- Wybory prezydenckie w Krakowie
        ('topic_c7158e8aa02efed22de467e3'),       -- Sondaż/wybory prezydenckie w Krakowie
        ('topic_merge_ec0fd008e1f82574be82de87')  -- UE i Polska: infrastruktura danych AI
) as selected(topic_id)
join public.topics t on t.topic_id = selected.topic_id
where t.status <> 'MERGED'
  and t.source_count >= 2
on conflict (topic_id, category) do nothing;
