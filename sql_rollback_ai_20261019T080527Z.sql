-- Jednorazowe cofniecie AI: harvest_20261019T080527Z.
-- Wklej CALY plik do Supabase -> SQL Editor -> Run, gdy workflow jest zatrzymany.
-- Zachowuje articles, run_articles, harvest_runs, aliasy URL i wyniki zrodel.
-- Odtwarza 13 starszych watkow / 162 powiazania z eksportu 2026-10-19 04:18 UTC.
-- Syntezy starszych watkow przywraca z topic_summary_versions, bez ich generowania.
-- Techniczne assigned_at/created_at przeniesionych starych przypisan zostaja
-- ustawione nie pozniej niz poprzednia analiza: eksport nie zawiera tych dat.
-- Nie jest to odtworzenie bajt w bajt calej bazy. Wszystkie zmiany sa atomowe.
-- Kopia cofanych danych zostaje w prywatnym schemacie gni_recovery.

do $rollback$
declare
    target_run constant text := 'harvest_20261019T080527Z';
    before_data constant jsonb := $baseline$[{"topic":{"topic_id":"topic_d998a873ba3dd5bc4119cf7a","headline_pl":"[Ukraina] Ograniczenia Starlink w Ukrainie","status":"ACTIVE","first_seen_at":"2026-10-13T08:26:25.021908+00:00","last_seen_at":"2026-10-18T09:17:38.975989+00:00","article_count":68,"source_count":29,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-18T10:56:26.257644+00:00","categories":["POLITYKA","SWIAT","TECHNOLOGIA"],"is_current":true},"links":[{"article_id":"015499a4de289d6ad53683a3","confidence":0.8125196753597169},{"article_id":"021e2c97668f03cafbe298bf","confidence":0.8125196753597169},{"article_id":"0426c036e077026518a3166c","confidence":0.8125196753597169},{"article_id":"054c4e2c1fbc3fbb3b6893d5","confidence":0.8125196753597169},{"article_id":"0b7a4c806a64e5dfe2248850","confidence":0.8125196753597169},{"article_id":"0f5429ea5566b3de796d3576","confidence":0.8125196753597169},{"article_id":"1299e05030147ef3356333b3","confidence":0.8125196753597169},{"article_id":"13b37f5d6fdde8df8c6c9b8e","confidence":0.8125196753597169},{"article_id":"160c783bc84727634d7cf4ca","confidence":0.8125196753597169},{"article_id":"1970f81b43420aa4e0990bd3","confidence":0.8125196753597169},{"article_id":"1dd6a3da9f718198cca1b157","confidence":0.8125196753597169},{"article_id":"24b8778df7140188e5e479fe","confidence":0.8125196753597169},{"article_id":"27f2333ac13273136448d6ab","confidence":0.8125196753597169},{"article_id":"281410ba3454ea5af39b4b5b","confidence":0.8125196753597169},{"article_id":"28b8bc63cae177a65e100d74","confidence":0.8125196753597169},{"article_id":"2e6435a1b275329d208e29f1","confidence":0.8125196753597169},{"article_id":"2fe2842a6b9041c650043bd4","confidence":0.8125196753597169},{"article_id":"309f5650934f28f99efa8e21","confidence":0.8125196753597169},{"article_id":"3a69a7d329bd967c0e34d50b","confidence":0.8125196753597169},{"article_id":"3acd6cc91df39cdfea910bfe","confidence":0.8125196753597169},{"article_id":"3ad763e9b3e46edd59c754d3","confidence":0.8125196753597169},{"article_id":"3decff14e5e53ba61baec0a2","confidence":0.8125196753597169},{"article_id":"3ec5592e8391dd078ab5f318","confidence":0.8125196753597169},{"article_id":"50369c0421eb2be744ca4b99","confidence":0.8125196753597169},{"article_id":"5dccdacb447bf2fc17eef285","confidence":0.8125196753597169},{"article_id":"61b8b7d6f12605f893f9f227","confidence":0.8125196753597169},{"article_id":"61fa42a98a665f4e370480de","confidence":0.8125196753597169},{"article_id":"7a00517fdb6b88ad10c01ba5","confidence":0.8125196753597169},{"article_id":"7bbfda465858b3c57ce6fdbd","confidence":0.8125196753597169},{"article_id":"7cf45a91f7e97a29edd1521c","confidence":0.8125196753597169},{"article_id":"7d4d480ef6d21aeb4462c7c8","confidence":0.8125196753597169},{"article_id":"89572e819c135c4039575626","confidence":0.8125196753597169},{"article_id":"932f32cb0afd8e51cf794c35","confidence":0.8125196753597169},{"article_id":"94a97b15099ce4a12780771b","confidence":0.8125196753597169},{"article_id":"9a27cd2a0ee18e300a0416d9","confidence":0.8125196753597169},{"article_id":"9b7539215f2589c9bdc7a221","confidence":0.8125196753597169},{"article_id":"9cdd6bceb1821bfa21a265d0","confidence":0.8125196753597169},{"article_id":"a0b7d3d425c2f44e6f1821f5","confidence":0.8125196753597169},{"article_id":"a1dd61fea4c620deefffe012","confidence":0.8125196753597169},{"article_id":"aa2b46632099daf2d8dfc0c9","confidence":0.8125196753597169},{"article_id":"aa9401810d3cd21841084934","confidence":0.8125196753597169},{"article_id":"accf3aa068ebcf46f43fde6c","confidence":0.8125196753597169},{"article_id":"b5432be70cb31acd106a81a3","confidence":0.8125196753597169},{"article_id":"b7ccb1ae6b235594005e7551","confidence":0.8125196753597169},{"article_id":"b960047b94e6ec1472810b0f","confidence":0.8125196753597169},{"article_id":"c5721e5eaae17d24948c297e","confidence":0.8125196753597169},{"article_id":"c815b85677280a0bad62b30e","confidence":0.8125196753597169},{"article_id":"cf33cc13e0e85a6a836095a5","confidence":0.8125196753597169},{"article_id":"d29a25ddd5b6c8499ad83812","confidence":0.8125196753597169},{"article_id":"d6f627d1326ed71c19b8f636","confidence":0.8125196753597169},{"article_id":"d7eb75bf5bead851faea1c69","confidence":0.8125196753597169},{"article_id":"d8209f1f4e15cececff274b8","confidence":0.8125196753597169},{"article_id":"dac48f92b175418d4e75e884","confidence":0.8125196753597169},{"article_id":"dc3a900c7264f1f69e628c33","confidence":0.8125196753597169},{"article_id":"df439d5511bbb2aa611bf41b","confidence":0.8125196753597169},{"article_id":"e280da0ef06d5c10c96bc3a6","confidence":0.8125196753597169},{"article_id":"e3c53f17e691a1e7b0c12640","confidence":0.8125196753597169},{"article_id":"e5ddd88bce5e87e672609d20","confidence":0.8125196753597169},{"article_id":"e6139242b7d6250cc5f0255e","confidence":0.8125196753597169},{"article_id":"e88c5d38ffc1409fc3600fee","confidence":0.8125196753597169},{"article_id":"ea49045de11a07d89ddecef0","confidence":0.8125196753597169},{"article_id":"ea7534600711d6b21d498a01","confidence":0.8125196753597169},{"article_id":"f1206bc08a2e9e0f9e9e35da","confidence":0.8125196753597169},{"article_id":"f3fa63b5e00dc8f2fe9a5c1f","confidence":0.8125196753597169},{"article_id":"f6007a6e2c8658ad971fda8a","confidence":0.8125196753597169},{"article_id":"f68815c0e4dd471de82aec79","confidence":0.8125196753597169},{"article_id":"fac69cae1295ffaa6431ee4d","confidence":0.8125196753597169},{"article_id":"fb5117e3777c07addab563e1","confidence":0.8125196753597169}],"summary_version":12,"summary_generated_at":"2026-10-18T10:58:06.223686+00:00"},{"topic":{"topic_id":"topic_b2a8853e542bb11c7e2c6b76","headline_pl":"[Ukraina] Apel Zelenskiego o wsparcie USA dla sankcji na Rosję","status":"ACTIVE","first_seen_at":"2026-10-15T04:11:00.803401+00:00","last_seen_at":"2026-10-19T04:00:43.974416+00:00","article_count":37,"source_count":22,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:05:12.587465+00:00","categories":["GOSPODARKA","POLITYKA","SWIAT"],"is_current":true},"links":[{"article_id":"003e48fbf57fedb00d01e7bf","confidence":0.7813407057776298},{"article_id":"09861c4a428b76f77d7db024","confidence":0.7813407057776298},{"article_id":"1653c280ce8562ab8edbce9b","confidence":0.7813407057776298},{"article_id":"1c384ffc4bc940dbb05ba69f","confidence":0.7813407057776298},{"article_id":"2d22fc56b03e4fe4920950c1","confidence":0.7813407057776298},{"article_id":"359463d5bb925a82fbe876be","confidence":0.7813407057776298},{"article_id":"43957390ba3e2e6856f28083","confidence":0.7813407057776298},{"article_id":"5387631de59c61bb1aa663c7","confidence":0.7813407057776298},{"article_id":"53908e305ca16237f1dddb01","confidence":0.7813407057776298},{"article_id":"53a99fad46e81fc31b13a5e5","confidence":0.7813407057776298},{"article_id":"574cc9ae3e0d54fc5ce0169d","confidence":0.7813407057776298},{"article_id":"6cba5410f0629e12d1fca69b","confidence":0.7813407057776298},{"article_id":"76fa54e5dd33ae40d519abe6","confidence":0.7813407057776298},{"article_id":"80d6804bf2edd3370c333342","confidence":0.7813407057776298},{"article_id":"8b38534e383d4ec2b7c4d976","confidence":0.7813407057776298},{"article_id":"930b0a0e9dd90126a4dbc48a","confidence":0.7813407057776298},{"article_id":"95100c15fdb2016141b557f5","confidence":0.7813407057776298},{"article_id":"970defc794f865a9eb4eb8ef","confidence":0.7813407057776298},{"article_id":"9ae4ffaffbe6a924d6b2f4c4","confidence":0.7813407057776298},{"article_id":"9b832b1c333d483d1f5e78f9","confidence":0.7813407057776298},{"article_id":"9bc37bfa332b99ec472d751a","confidence":0.7813407057776298},{"article_id":"a6ec3a0f7f7fa310f5a0ec6f","confidence":0.7813407057776298},{"article_id":"b131324d5488f7279d143f3e","confidence":0.7813407057776298},{"article_id":"b3defd2a1badec11547fe6da","confidence":0.7813407057776298},{"article_id":"b40279cdc359d5fa70209d87","confidence":0.7813407057776298},{"article_id":"b530e1693a89d7cc8694d89d","confidence":0.7813407057776298},{"article_id":"b74bdd9d55181f519a71301b","confidence":0.7813407057776298},{"article_id":"c115b414b3ad983457b360d7","confidence":0.7813407057776298},{"article_id":"c6b001496990d7676b249ea5","confidence":0.7813407057776298},{"article_id":"c6e5c9d4d7a543065b7e0f13","confidence":0.7813407057776298},{"article_id":"d498227b09a403cc2e23d87d","confidence":0.7813407057776298},{"article_id":"d515721c9f21bcf93b1287e3","confidence":0.7813407057776298},{"article_id":"df90815990a5382978000292","confidence":0.7813407057776298},{"article_id":"f3ce3561d700c913c4aee102","confidence":0.7813407057776298},{"article_id":"f3d3e1644577454c1dbb13d9","confidence":0.7813407057776298},{"article_id":"f6b0745625a4919c78333631","confidence":0.7813407057776298},{"article_id":"fe4d9e9ef31cd84c0bcc4a62","confidence":0.7813407057776298}],"summary_version":5,"summary_generated_at":"2026-10-19T04:08:55.291173+00:00"},{"topic":{"topic_id":"topic_ea5b90e9f85a33a108f2e78b","headline_pl":"[Świat] Atak izraelskich osadników na europejskie samochody dyplomatyczne na Zachodnim Brzegu","status":"ACTIVE","first_seen_at":"2026-10-17T16:02:35.02719+00:00","last_seen_at":"2026-10-18T09:17:26.109905+00:00","article_count":6,"source_count":6,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-18T09:17:26.109905+00:00","categories":["POLITYKA","SWIAT"],"is_current":true},"links":[{"article_id":"2719e099b05bce706d7c130a","confidence":0.8292800636605397},{"article_id":"287a3bba93dffc4d537bac8c","confidence":0.8292800636605397},{"article_id":"4fc4c4f1068d42e191a54a2d","confidence":0.8292800636605397},{"article_id":"a19c663c1daf2c407a4f3cce","confidence":0.8292800636605397},{"article_id":"ad1468123827757598248a5d","confidence":0.8292800636605397},{"article_id":"d6a7125942beb3c74fa8f9df","confidence":0.8292800636605397}],"summary_version":1,"summary_generated_at":"2026-10-18T09:17:26.109905+00:00"},{"topic":{"topic_id":"topic_e04ea4e4b5cb00fcf8cbc3c7","headline_pl":"[Polska] Przeszukiwanie terenu przy Zalewie Zemborzyckim","status":"ACTIVE","first_seen_at":"2026-10-18T09:05:26.446855+00:00","last_seen_at":"2026-10-19T04:13:20.386667+00:00","article_count":3,"source_count":2,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:13:20.386667+00:00","categories":["POLSKA","SPOLECZENSTWO"],"is_current":true},"links":[{"article_id":"1b9342d6294d9b362e818fe4","confidence":0.832730597748935},{"article_id":"bbe571eb7b5cd24f6b8ff92c","confidence":0.832730597748935},{"article_id":"c5e037b3c4a011a3a76f6048","confidence":0.832730597748935}],"summary_version":1,"summary_generated_at":"2026-10-19T04:13:20.386667+00:00"},{"topic":{"topic_id":"topic_2ed6a2745cc7deaddab534d1","headline_pl":"[Polska] Naruszenie polskiej przestrzeni powietrznej","status":"ACTIVE","first_seen_at":"2026-10-18T09:05:40.442177+00:00","last_seen_at":"2026-10-18T16:06:10.994096+00:00","article_count":4,"source_count":4,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:05:14.871212+00:00","categories":["POLITYKA","POLSKA"],"is_current":true},"links":[{"article_id":"341a3d396243003bab7a23db","confidence":0.8517747299414479},{"article_id":"37a430390e656876b813f7b4","confidence":0.8517747299414479},{"article_id":"845ac47720bd6eb85d8ac4ba","confidence":0.8517747299414479},{"article_id":"de7f7fbb543616112ab4caa5","confidence":0.8517747299414479}],"summary_version":2,"summary_generated_at":"2026-10-19T04:09:48.01714+00:00"},{"topic":{"topic_id":"topic_1b31aa0aa6f7a80891a15f07","headline_pl":"[Europa] Macron o karaniu za przemoc w protestach","status":"ACTIVE","first_seen_at":"2026-10-18T09:07:36.978691+00:00","last_seen_at":"2026-10-19T04:11:54.374758+00:00","article_count":4,"source_count":4,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:11:54.374758+00:00","categories":["POLITYKA","SWIAT"],"is_current":true},"links":[{"article_id":"22a99fac6b03343696bff3ea","confidence":0.8295563179405853},{"article_id":"a713ec9db5f70cf855a280dd","confidence":0.8295563179405853},{"article_id":"c87c66696ffc94dd205e1cad","confidence":0.8295563179405853},{"article_id":"f5fe618fd739bf23d947eb82","confidence":0.8295563179405853}],"summary_version":1,"summary_generated_at":"2026-10-19T04:11:54.374758+00:00"},{"topic":{"topic_id":"topic_8f582c00cb3d84452e9c0991","headline_pl":"[Polska] Kontrowersje po zatrzymaniu Piotra W.","status":"ACTIVE","first_seen_at":"2026-10-17T15:59:48.468846+00:00","last_seen_at":"2026-10-19T03:57:34.565055+00:00","article_count":19,"source_count":6,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:05:16.905767+00:00","categories":["POLITYKA","POLSKA","SPOLECZENSTWO"],"is_current":true},"links":[{"article_id":"07dd64f78e361d75b83ab8ae","confidence":0.8398281515686653},{"article_id":"25867d0f20ebb7a80daeaa62","confidence":0.8398281515686653},{"article_id":"25d7e592380a51f873a01457","confidence":0.8398281515686653},{"article_id":"3cb53b2a3fd253788bab1344","confidence":0.8398281515686653},{"article_id":"69b1392dd17fd74bb5934759","confidence":0.8398281515686653},{"article_id":"6b96d506cdfa160713835aab","confidence":0.8398281515686653},{"article_id":"74ed269ea175d1254250a00e","confidence":0.8398281515686653},{"article_id":"811630bb27e18f79292db734","confidence":0.8398281515686653},{"article_id":"9582d0454ef8af893e6ded88","confidence":0.8398281515686653},{"article_id":"98b036803ae38d246733799f","confidence":0.8398281515686653},{"article_id":"9cbf792827f4fcced1afa157","confidence":0.8398281515686653},{"article_id":"b03d03c6bcaade7a9a8ba98a","confidence":0.8398281515686653},{"article_id":"b49f65b4c2501bb896ac7faa","confidence":0.8398281515686653},{"article_id":"b725b0dd766c774e458d4690","confidence":0.8398281515686653},{"article_id":"caaf35633a0b3b54e72d9bc2","confidence":0.8398281515686653},{"article_id":"d040a06570847ef469ef84f7","confidence":0.8398281515686653},{"article_id":"d66b35bf74c16b9299ea38c2","confidence":0.8398281515686653},{"article_id":"e0ea1bb962309d84847b1410","confidence":0.8398281515686653},{"article_id":"ed135993e37dd639b7cb98a3","confidence":0.8398281515686653}],"summary_version":3,"summary_generated_at":"2026-10-19T04:08:45.650189+00:00"},{"topic":{"topic_id":"topic_eb20f2236c88d2a7b60465b3","headline_pl":"[Polska] Kaczyński o decyzji sądu w sprawie Piotra W.","status":"ACTIVE","first_seen_at":"2026-10-18T15:54:09.147957+00:00","last_seen_at":"2026-10-19T04:13:06.299522+00:00","article_count":3,"source_count":3,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:13:06.299522+00:00","categories":["POLITYKA","POLSKA"],"is_current":true},"links":[{"article_id":"15fba31902f143c58dbbbb8a","confidence":0.8475293958250918},{"article_id":"e59afcd6d37b6539294e8c53","confidence":0.8475293958250918},{"article_id":"f441c1340861a01e89a2c668","confidence":0.8475293958250918}],"summary_version":1,"summary_generated_at":"2026-10-19T04:13:06.299522+00:00"},{"topic":{"topic_id":"topic_e816998be76165dd57c43ef1","headline_pl":"[Francja] Macron po zamieszkach i aresztach","status":"ACTIVE","first_seen_at":"2026-10-18T15:55:16.893596+00:00","last_seen_at":"2026-10-19T03:59:57.957347+00:00","article_count":6,"source_count":6,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:05:18.438844+00:00","categories":["POLITYKA","SWIAT"],"is_current":true},"links":[{"article_id":"1711049282aa1dffbebb3689","confidence":0.8236159368651664},{"article_id":"184eb6c3c47c675a2bc5d1eb","confidence":0.8236159368651664},{"article_id":"649b9db04f574cbb16e6bf32","confidence":0.8236159368651664},{"article_id":"6c3af5e7183456f65e4babb0","confidence":0.8236159368651664},{"article_id":"a89dfc7b330e0eebb468c275","confidence":0.8236159368651664},{"article_id":"ce5c19a0bc1bbe38f458202b","confidence":0.8236159368651664}],"summary_version":2,"summary_generated_at":"2026-10-19T04:08:29.538868+00:00"},{"topic":{"topic_id":"topic_801564326c9f91d4056598d5","headline_pl":"[Świat] Krytyka działań Trumpa dotyczących Rosji i Ukrainy","status":"ACTIVE","first_seen_at":"2026-10-18T15:54:40.820018+00:00","last_seen_at":"2026-10-19T04:11:27.551892+00:00","article_count":3,"source_count":3,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:11:27.551892+00:00","categories":["POLITYKA","SWIAT"],"is_current":true},"links":[{"article_id":"08b1af0d8ad34595799e35d5","confidence":0.799874128601963},{"article_id":"bb0beefbb4e526d4b6034bff","confidence":0.799874128601963},{"article_id":"c587f0414a84fd9b129bae85","confidence":0.799874128601963}],"summary_version":1,"summary_generated_at":"2026-10-19T04:11:27.551892+00:00"},{"topic":{"topic_id":"topic_a19d760c739f5add025ce8d2","headline_pl":"[Izrael] Atak osadników na dziennikarza","status":"ACTIVE","first_seen_at":"2026-10-18T15:55:59.794376+00:00","last_seen_at":"2026-10-19T04:14:48.317776+00:00","article_count":2,"source_count":2,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:14:48.317776+00:00","categories":["POLITYKA","SPOLECZENSTWO","SWIAT"],"is_current":true},"links":[{"article_id":"7ef833c2e86eb76cdead4659","confidence":0.841704159060192},{"article_id":"942725b90fbd450920116676","confidence":0.841704159060192}],"summary_version":1,"summary_generated_at":"2026-10-19T04:14:48.317776+00:00"},{"topic":{"topic_id":"topic_ffd402f207f95f003a411a99","headline_pl":"[Świat] Groźby USA wobec UE dotyczące Starlinka","status":"ACTIVE","first_seen_at":"2026-10-19T03:56:59.807836+00:00","last_seen_at":"2026-10-19T04:15:37.985902+00:00","article_count":2,"source_count":2,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:15:37.985902+00:00","categories":["POLITYKA","SWIAT","TECHNOLOGIA"],"is_current":true},"links":[{"article_id":"5ccecc8736979b0c164e592d","confidence":0.8215764358877746},{"article_id":"dde84af7788ce636f66beefe","confidence":0.8215764358877746}],"summary_version":1,"summary_generated_at":"2026-10-19T04:15:37.985902+00:00"},{"topic":{"topic_id":"topic_2862028e182b1c40072fe3ec","headline_pl":"[Świat] Działania Trumpa w kontekście Ukrainy","status":"ACTIVE","first_seen_at":"2026-10-19T03:56:59.807836+00:00","last_seen_at":"2026-10-19T04:10:56.797144+00:00","article_count":5,"source_count":4,"coverage_status":"MULTI_SOURCE","needs_review":false,"merged_into_topic_id":null,"merged_at":null,"updated_at":"2026-10-19T04:10:56.797144+00:00","categories":["POLITYKA","SWIAT"],"is_current":true},"links":[{"article_id":"25331aa985a5aab755dad5ac","confidence":0.8227216206521292},{"article_id":"77bd518deb730949520d070f","confidence":0.8227216206521292},{"article_id":"936accbbb07c03eaabde8175","confidence":0.8227216206521292},{"article_id":"a14a36729cadd29f2b736699","confidence":0.8227216206521292},{"article_id":"ada26103e24046c9e80ff3b9","confidence":0.8227216206521292}],"summary_version":1,"summary_generated_at":"2026-10-19T04:10:56.797144+00:00"}]$baseline$::jsonb;
    after_export constant timestamptz := '2026-10-19T08:42:42.354386+00:00';
    started timestamptz;
    new_ids text[];
    old_ids text[];
    excluded_ids text[];
    all_ids text[];
    before_articles bigint;
    backup_data jsonb;
begin
    -- Zapobiega rownoleglym zapisom w trakcie cofania. Nie uruchamiaj workflow
    -- pomiedzy wykonaniem tego SQL a ponownym uruchomieniem ai-only.
    lock table public.harvest_runs in share mode;
    lock table public.topics, public.topic_articles, public.article_topic_assignments,
        public.topic_summaries, public.topic_summary_versions, public.topic_categories,
        public.topic_runs, public.articles in share row exclusive mode;

    create schema if not exists gni_recovery;
    revoke all on schema gni_recovery from public, anon, authenticated;
    create table if not exists gni_recovery.ai_rollbacks (
        run_id text primary key,
        saved_at timestamptz not null default now(),
        completed_at timestamptz,
        payload jsonb not null,
        result jsonb
    );
    revoke all on gni_recovery.ai_rollbacks from public, anon, authenticated;
    if exists (select 1 from gni_recovery.ai_rollbacks r
               where r.run_id = target_run and r.completed_at is not null) then
        raise notice 'Ten SQL zostal juz wykonany. Niczego ponownie nie usuwam.';
        return;
    end if;

    select h.started_at into started from public.harvest_runs h where h.run_id = target_run;
    if started is null then raise exception 'Nie ma przebiegu %.', target_run; end if;
    if exists (select 1 from public.harvest_runs h where h.started_at > started) then
        raise exception 'Istnieje nowszy harvest. Nie cofam danych na podstawie starszej kopii.';
    end if;
    if exists (select 1 from public.topic_runs r where r.created_at > after_export)
       or exists (select 1 from public.topic_summary_versions v where v.generated_at > after_export)
       or exists (select 1 from public.topics t where t.updated_at > after_export) then
        raise exception 'Po eksporcie zapisano dalsze wyniki AI lub zmiany watkow. Cofanie przerwane bez zmian.';
    end if;

    select array_agg(b->'topic'->>'topic_id') into old_ids from jsonb_array_elements(before_data) b;
    select array_agg(t.topic_id) into new_ids from public.topics t
    where t.first_seen_at >= started and t.first_seen_at <= after_export
      and t.topic_id like 'topic_perspectives_%';
    if coalesce(cardinality(new_ids), 0) <> 286 then
        raise exception 'Oczekiwano 286 nowych kandydatow, znaleziono %. Baza ma inny stan; nic nie usunieto.', cardinality(new_ids);
    end if;
    if (select count(*) from public.article_topic_assignments a where a.run_id = target_run) <> 286
       or exists (select 1 from public.article_topic_assignments a
                  where a.run_id = target_run and not (a.topic_id = any(new_ids))) then
        raise exception 'Przypisania tego przebiegu nie odpowiadaja logom. Nic nie usunieto.';
    end if;
    select array_agg(distinct d.key) into excluded_ids
    from public.topic_runs r
    cross join lateral jsonb_each(coalesce(r.raw_output->'parsed', r.raw_output)->'decisions') d
    where r.run_id = target_run and r.stage = 'LABELING' and r.status = 'COMPLETED'
      and d.value->>'category' <> 'KEEP';
    if coalesce(cardinality(excluded_ids), 0) <> 142 then
        raise exception 'Oczekiwano 142 odrzuconych artykulow w historii LABELING. Nic nie usunieto.';
    end if;
    if exists (select 1 from jsonb_array_elements(before_data) b
               where not exists (select 1 from public.topic_summary_versions v
                 where v.topic_id = b->'topic'->>'topic_id'
                   and v.version = (b->>'summary_version')::integer)
                  or not exists (select 1 from public.topics t where t.topic_id = b->'topic'->>'topic_id')) then
        raise exception 'Brakuje starszego watku lub jego zapisanej wersji syntezy. Przywrocenie przerwane bez zmian.';
    end if;
    all_ids := new_ids || old_ids;
    -- Starsze przekierowania do old_ids pozostaja poprawne: te watki
    -- przywracamy, a nie usuwamy. Blokujemy tylko zewnetrzne referencje
    -- do nowych kandydatow przeznaczonych do usuniecia.
    if exists (select 1 from public.topics t where t.merged_into_topic_id = any(new_ids)
               and not (t.topic_id = any(all_ids))) then
        raise exception 'Tematy spoza zakresu wskazuja na NOWE watki przeznaczone do usuniecia. Nic nie usunieto.';
    end if;
    select count(*) into before_articles from public.articles;
    select jsonb_build_object(
        'topics', (select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.topics t where t.topic_id = any(all_ids)),
        'topic_articles', (select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.topic_articles t where t.topic_id = any(all_ids)),
        'assignments', (select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.article_topic_assignments t where t.topic_id = any(all_ids) or t.run_id = target_run),
        'summaries', (select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.topic_summaries t where t.topic_id = any(all_ids)),
        'versions', (select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.topic_summary_versions t where t.topic_id = any(all_ids)),
        'categories', (select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.topic_categories t where t.topic_id = any(all_ids)),
        'topic_runs', (select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.topic_runs t where t.run_id = target_run),
        'article_hints', (select coalesce(jsonb_agg(jsonb_build_object('article_id', a.article_id, 'topic_hint', a.topic_hint)), '[]'::jsonb)
                          from public.articles a where a.article_id = any(excluded_ids)),
        'new_topic_ids', to_jsonb(new_ids), 'baseline', before_data
    ) into backup_data;
    insert into gni_recovery.ai_rollbacks(run_id, payload) values (target_run, backup_data);

    -- Przed cofnieciem przekierowan odtwarzamy metadane 13 starszych watkow.
    update public.topics t set
        headline_pl = b->'topic'->>'headline_pl', status = 'ACTIVE',
        first_seen_at = (b->'topic'->>'first_seen_at')::timestamptz,
        last_seen_at = (b->'topic'->>'last_seen_at')::timestamptz,
        article_count = (b->'topic'->>'article_count')::integer,
        source_count = (b->'topic'->>'source_count')::integer,
        coverage_status = b->'topic'->>'coverage_status',
        needs_review = (b->'topic'->>'needs_review')::boolean,
        merged_into_topic_id = b->'topic'->>'merged_into_topic_id',
        merged_at = (b->'topic'->>'merged_at')::timestamptz,
        updated_at = (b->'topic'->>'updated_at')::timestamptz
    from jsonb_array_elements(before_data) b where t.topic_id = b->'topic'->>'topic_id';

    delete from public.article_topic_assignments a where a.run_id = target_run;
    update public.article_topic_assignments a set
        topic_id = b->'topic'->>'topic_id',
        created_at = least(a.created_at, (b->>'summary_generated_at')::timestamptz)
    from jsonb_array_elements(before_data) b
    cross join lateral jsonb_array_elements(b->'links') l
    where a.article_id = l->>'article_id';
    if exists (select 1 from public.article_topic_assignments a where a.topic_id = any(new_ids)) then
        raise exception 'Nowe watki maja przypisania z innych przebiegow; wycofano cala operacje.';
    end if;
    delete from public.topic_articles t where t.topic_id = any(all_ids);
    insert into public.topic_articles(topic_id, article_id, confidence, assigned_at)
    select b->'topic'->>'topic_id', l->>'article_id', (l->>'confidence')::numeric,
        coalesce((select min(a.created_at) from public.article_topic_assignments a
                   where a.topic_id = b->'topic'->>'topic_id' and a.article_id = l->>'article_id'),
                 (b->>'summary_generated_at')::timestamptz)
    from jsonb_array_elements(before_data) b cross join lateral jsonb_array_elements(b->'links') l;

    insert into public.topic_summaries(topic_id, version, input_hash, model, summary, generated_at, updated_at)
    select v.topic_id, v.version,
        coalesce((select s.input_hash from public.topic_summaries s where s.topic_id = v.topic_id and s.version = v.version), 'restored-before-' || target_run),
        v.model, v.summary, v.generated_at, v.generated_at
    from jsonb_array_elements(before_data) b join public.topic_summary_versions v
      on v.topic_id = b->'topic'->>'topic_id' and v.version = (b->>'summary_version')::integer
    on conflict (topic_id) do update set version = excluded.version, input_hash = excluded.input_hash,
        model = excluded.model, summary = excluded.summary,
        generated_at = excluded.generated_at, updated_at = excluded.updated_at;
    delete from public.topic_summary_versions v where v.run_id = target_run or v.topic_id = any(new_ids);
    delete from public.topic_summaries s where s.topic_id = any(new_ids);
    delete from public.topic_categories c where c.topic_id = any(all_ids);
    insert into public.topic_categories(topic_id, category)
    select b->'topic'->>'topic_id', c.value
    from jsonb_array_elements(before_data) b
    cross join lateral jsonb_array_elements_text(b->'topic'->'categories') c(value);
    -- Usun przekierowania pomiedzy nowymi kandydatami przed usunieciem FK.
    update public.topics t set merged_into_topic_id = null, merged_at = null where t.topic_id = any(new_ids);
    delete from public.topics t where t.topic_id = any(new_ids);
    update public.articles a set topic_hint = null
      where a.article_id = any(excluded_ids) and a.topic_hint like 'AI_EXCLUDED:%';
    delete from public.topic_runs r where r.run_id = target_run;

    if (select count(*) from public.articles) <> before_articles then
        raise exception 'Zmiana liczby artykulow; wycofano cala operacje.';
    end if;
    update gni_recovery.ai_rollbacks r set completed_at = now(), result = jsonb_build_object(
        'run_id', target_run, 'usuniete_nowe_watki', cardinality(new_ids),
        'przywrocone_starsze_watki', cardinality(old_ids),
        'wyczyszczone_decyzje_o_odrzuceniu', cardinality(excluded_ids),
        'artykuly_zachowane_w_bazie', before_articles,
        'przywrocone_powiazania', 162,
        'artykuly_tego_przebiegu_starsze_niz_24h', (select count(*) from public.run_articles ra
            join public.articles a on a.article_id = ra.article_id
            where ra.run_id = target_run and ra.fetched_now and a.fetched_at < now() - interval '24 hours')
    ) where r.run_id = target_run;
end
$rollback$;

select result as wynik_cofniecia from gni_recovery.ai_rollbacks
where run_id = 'harvest_20261019T080527Z';
