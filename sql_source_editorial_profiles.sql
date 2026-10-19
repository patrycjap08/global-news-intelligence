-- Tylko odczyt: aktualne przypisania do przeglądu przed ewentualną korektą.
select name as zrodlo, enabled as wlaczone,
       editorial_profile as obecny_profil, source_type as typ_zrodla,
       case
         when editorial_profile in ('STATE_ALIGNED', 'STATE_MEDIA') or source_type = 'STATE_MEDIA'
           then 'Kontrolowane przez państwo — do potwierdzenia'
         when editorial_profile in ('LEFT', 'CENTER_LEFT') then 'Lewicowe'
         when editorial_profile in ('RIGHT', 'CENTER_RIGHT') then 'Prawicowe'
         when editorial_profile = 'CENTER' then 'Centrum'
         else 'Do sklasyfikowania'
       end as grupa
from public.sources
order by enabled desc, grupa, name;
