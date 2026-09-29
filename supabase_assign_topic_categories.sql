-- Kategorie wybrane na podstawie eksportu 50 tematów z 29.09.2026.
-- Relacja wiele–wiele: jeden temat może mieć kilka kategorii.
-- Skrypt jest bezpieczny do ponownego uruchomienia i nie kasuje istniejących przypisań.

begin;

insert into public.topic_categories (topic_id, category)
values
    ('topic_ff95334c4fd96a63d7a62b3f', 'POLITYKA'),
    ('topic_ff95334c4fd96a63d7a62b3f', 'SWIAT'),

    ('topic_a8a3d68f25096395697d5380', 'SPOLECZENSTWO'),
    ('topic_a8a3d68f25096395697d5380', 'POLITYKA'),

    ('topic_cc72c3c67b1f0855f14976de', 'GOSPODARKA'),

    ('topic_6bbb67ab1f3a02bd98f39f61', 'TECHNOLOGIA'),
    ('topic_6bbb67ab1f3a02bd98f39f61', 'GOSPODARKA'),

    ('topic_6d84b584e61a64d14e8a84e4', 'POLITYKA'),

    ('topic_merge_c24ebd810db39d6731cc701f', 'POLITYKA'),

    ('topic_merge_74a21a815916117108fc1051', 'SPOLECZENSTWO'),
    ('topic_merge_74a21a815916117108fc1051', 'POLITYKA'),

    ('topic_merge_4e526552e0fe594386a804eb', 'POLITYKA'),
    ('topic_merge_4e526552e0fe594386a804eb', 'GOSPODARKA'),

    ('topic_merge_53f0b0be764c000cc548fc30', 'POLITYKA'),

    ('topic_merge_65f4dae80a8141264da043a4', 'POLITYKA'),
    ('topic_merge_65f4dae80a8141264da043a4', 'SWIAT'),

    ('topic_c2756d3f4d2e0bbf87d7a200', 'TECHNOLOGIA'),

    ('topic_merge_bf4339277095a2a79614a225', 'TECHNOLOGIA'),

    ('topic_221946f95a58e84657c70ae3', 'SPOLECZENSTWO'),
    ('topic_221946f95a58e84657c70ae3', 'POLITYKA'),

    ('topic_21bea252eb9a1bce7174ce9b', 'POLITYKA'),
    ('topic_21bea252eb9a1bce7174ce9b', 'SWIAT'),

    ('topic_merge_8d8e2ddc4ae12f9179013cb5', 'POLITYKA'),

    ('topic_cdf1e2c94977fbfff6e166ff', 'POLITYKA'),
    ('topic_cdf1e2c94977fbfff6e166ff', 'SPOLECZENSTWO'),

    ('topic_9711f2dbbfa34e9cc8a8a72b', 'POLITYKA'),

    ('topic_9ee95916c0538dd9c8b7ae16', 'TECHNOLOGIA'),

    ('topic_4ae28420b7495e076be86d3b', 'POLITYKA'),
    ('topic_4ae28420b7495e076be86d3b', 'SPOLECZENSTWO'),

    ('topic_f727d6aa25f4b56d43e217a6', 'SWIAT'),
    ('topic_f727d6aa25f4b56d43e217a6', 'POLITYKA'),

    ('topic_merge_fbe95452ddd6adc8e3da5ff3', 'SWIAT'),
    ('topic_merge_fbe95452ddd6adc8e3da5ff3', 'GOSPODARKA'),
    ('topic_merge_fbe95452ddd6adc8e3da5ff3', 'TECHNOLOGIA'),

    ('topic_06aa298de0ed60f64963b592', 'POLITYKA'),
    ('topic_06aa298de0ed60f64963b592', 'GOSPODARKA'),

    ('topic_4afbea7c1562781d51b3027c', 'POLITYKA'),
    ('topic_4afbea7c1562781d51b3027c', 'GOSPODARKA'),

    ('topic_merge_3a3b6144d7c5a4513fda877d', 'POLITYKA'),
    ('topic_merge_3a3b6144d7c5a4513fda877d', 'SPOLECZENSTWO'),

    ('topic_620565d1fdee4142f4531f89', 'SPOLECZENSTWO'),
    ('topic_620565d1fdee4142f4531f89', 'POLITYKA'),

    ('topic_0d80ae4aa93f964051333e95', 'GOSPODARKA'),

    ('topic_merge_1418c2d075cf989cc786d440', 'SWIAT'),
    ('topic_merge_1418c2d075cf989cc786d440', 'GOSPODARKA'),
    ('topic_merge_1418c2d075cf989cc786d440', 'TECHNOLOGIA'),

    ('topic_c7158e8aa02efed22de467e3', 'POLITYKA'),

    ('topic_merge_e925e98ca76202c34de14cd3', 'SPOLECZENSTWO'),
    ('topic_merge_e925e98ca76202c34de14cd3', 'POLITYKA'),

    ('topic_merge_3aa4cab72379d6314bc3c9b4', 'POLITYKA'),

    ('topic_merge_02c7781672138b3bf6d091dc', 'POLITYKA'),

    ('916df8eb8f5293e770361aba', 'SPOLECZENSTWO'),
    ('916df8eb8f5293e770361aba', 'POLITYKA'),

    ('topic_9cb2976996dff04748f0e526', 'TECHNOLOGIA'),
    ('topic_9cb2976996dff04748f0e526', 'SWIAT'),

    ('topic_merge_d0b61b836c3d2a9fa875473d', 'SPOLECZENSTWO'),
    ('topic_merge_d0b61b836c3d2a9fa875473d', 'POLITYKA'),

    ('topic_eac7e3d6bc4b331e10c153ae', 'GOSPODARKA'),
    ('topic_eac7e3d6bc4b331e10c153ae', 'SWIAT'),
    ('topic_eac7e3d6bc4b331e10c153ae', 'POLITYKA'),

    ('topic_d04f2ae1e7e5b09e3ed007d2', 'SWIAT'),
    ('topic_d04f2ae1e7e5b09e3ed007d2', 'POLITYKA'),

    ('topic_dce34ed098d62eca485498f1', 'TECHNOLOGIA'),
    ('topic_dce34ed098d62eca485498f1', 'SPOLECZENSTWO'),

    ('topic_5f1a53a3dea99ca895ea18d0', 'POLITYKA'),
    ('topic_5f1a53a3dea99ca895ea18d0', 'SPOLECZENSTWO'),

    ('topic_8132c65f3d77ee56d1b9f84e', 'SPOLECZENSTWO'),

    ('topic_merge_ae3ce967a0b65072c5edd2cd', 'POLITYKA'),
    ('topic_merge_ae3ce967a0b65072c5edd2cd', 'SWIAT'),

    ('topic_846f90436888b15e32c24dee', 'KULTURA_SPORT'),
    ('topic_846f90436888b15e32c24dee', 'POLITYKA'),

    ('topic_90eed5a22ec25cc69747b0e7', 'SWIAT'),

    ('topic_cc6a828212f550ede026de34', 'TECHNOLOGIA'),
    ('topic_cc6a828212f550ede026de34', 'SPOLECZENSTWO'),

    ('topic_72896b0902bf5e95409db838', 'SPOLECZENSTWO'),

    ('topic_06470d2dedcc6d66737aa16a', 'SWIAT'),
    ('topic_06470d2dedcc6d66737aa16a', 'POLITYKA'),

    ('topic_f87f78512e5b809e23916a3a', 'SWIAT'),
    ('topic_f87f78512e5b809e23916a3a', 'GOSPODARKA'),

    ('topic_3769812689925b61ed08c5b7', 'SPOLECZENSTWO'),

    ('topic_cedeff47a5771721942ff5cd', 'SWIAT'),
    ('topic_cedeff47a5771721942ff5cd', 'POLITYKA'),

    ('topic_0a67d58f3f2a6821925d03e1', 'TECHNOLOGIA'),
    ('topic_0a67d58f3f2a6821925d03e1', 'GOSPODARKA'),
    ('topic_0a67d58f3f2a6821925d03e1', 'POLITYKA'),

    ('topic_3d24988e71021b18098923a1', 'SPOLECZENSTWO')
on conflict (topic_id, category) do nothing;

commit;

