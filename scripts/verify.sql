-- Post-load verification. Run through the Supabase MCP (execute_sql).
--
-- The expected numbers come from the "valores dimensiones" pivot tab of the
-- source workbook, which was built independently of our pipeline. Every row
-- below must read PASS; a FAIL means the load is wrong, not the check.

with checks as (
  select 'brands = 28'            as prueba, (select count(*) from brands)::text as got, '28'   as want
  union all select 'models = 1483',  (select count(*) from models)::text, '1483'
  union all select 'skus = 24109',   (select count(*) from skus)::text,   '24109'

  -- Tipo de producto
  union all select 'running = 984',  (select count(*) from models where tipo_producto = 'zapatilla running hombre')::text, '984'
  union all select 'trail = 499',    (select count(*) from models where tipo_producto = 'zapatillas trail hombre')::text,  '499'

  -- Nivel de margen
  union all select 'margen muy bajo = 287', (select count(*) from models where nivel_margen = 'muy bajo')::text, '287'
  union all select 'margen bajo = 261',     (select count(*) from models where nivel_margen = 'bajo')::text,     '261'
  union all select 'margen medio = 601',    (select count(*) from models where nivel_margen = 'medio')::text,    '601'
  union all select 'margen alto = 334',     (select count(*) from models where nivel_margen = 'alto')::text,     '334'

  -- Nivel de stock
  union all select 'stock muy alto = 58',   (select count(*) from models where nivel_stock = 'muy alto')::text, '58'
  union all select 'stock alto = 63',       (select count(*) from models where nivel_stock = 'alto')::text,     '63'
  union all select 'stock medio = 66',      (select count(*) from models where nivel_stock = 'medio')::text,    '66'
  union all select 'stock bajo = 269',      (select count(*) from models where nivel_stock = 'bajo')::text,     '269'
  union all select 'stock muy bajo = 1027', (select count(*) from models where nivel_stock = 'muy bajo')::text, '1027'

  -- Gestión
  union all select 'outlet SI = 112',        (select count(*) from models where outlet)::text,           '112'
  union all select 'outlet NO = 1371',       (select count(*) from models where not outlet)::text,       '1371'
  union all select 'cat_extendido = 478',    (select count(*) from models where cat_extendido)::text,    '478'
  union all select 'exclusivo_online = 682', (select count(*) from models where exclusivo_online)::text, '682'

  -- Temporada
  union all select 'temporada AN = 48',   (select count(*) from models where temporada = 'AN')::text, '48'
  union all select 'temporada OI = 1040', (select count(*) from models where temporada = 'OI')::text, '1040'
  union all select 'temporada PV = 395',  (select count(*) from models where temporada = 'PV')::text, '395'

  -- Clasificación ABCD tienda
  union all select 'abcd_tienda AA = 6',    (select count(*) from models where abcd_tienda = 'AA')::text,   '6'
  union all select 'abcd_tienda A = 14',    (select count(*) from models where abcd_tienda = 'A')::text,    '14'
  union all select 'abcd_tienda B = 43',    (select count(*) from models where abcd_tienda = 'B')::text,    '43'
  union all select 'abcd_tienda C = 234',   (select count(*) from models where abcd_tienda = 'C')::text,    '234'
  union all select 'abcd_tienda D = 892',   (select count(*) from models where abcd_tienda = 'D')::text,    '892'
  union all select 'abcd_tienda NULL = 294',(select count(*) from models where abcd_tienda is null)::text,  '294'

  -- Clasificación ABCD digital
  union all select 'abcd_digital AA = 9',    (select count(*) from models where abcd_digital = 'AA')::text,  '9'
  union all select 'abcd_digital A = 60',    (select count(*) from models where abcd_digital = 'A')::text,   '60'
  union all select 'abcd_digital B = 143',   (select count(*) from models where abcd_digital = 'B')::text,   '143'
  union all select 'abcd_digital C = 215',   (select count(*) from models where abcd_digital = 'C')::text,   '215'
  union all select 'abcd_digital D = 762',   (select count(*) from models where abcd_digital = 'D')::text,   '762'
  union all select 'abcd_digital NULL = 294',(select count(*) from models where abcd_digital is null)::text, '294'

  -- Limpieza de centinelas (grano de modelo)
  union all select 'cobertura NULL = 249',   (select count(*) from models where cobertura_stock is null)::text, '249'
  union all select 'color NULL = 23',        (select count(*) from models where color is null)::text,           '23'
  union all select 'custom_label NULL = 183',(select count(*) from models where custom_label is null)::text,     '183'
  union all select 'ano 9998 = 2',           (select count(*) from models where ano_temporada = 9998)::text,     '2'

  -- Derivados e integridad
  union all select 'en_rebaja = 824',      (select count(*) from models where en_rebaja)::text, '824'
  union all select 'eans unicos',          (select count(distinct ean) from skus)::text,        '24109'
  union all select 'skus huerfanos = 0',
    (select count(*) from skus s left join models m on m.modelo = s.modelo where m.modelo is null)::text, '0'
  union all select 'modelos sin sku = 0',
    (select count(*) from models m left join skus s on s.modelo = m.modelo where s.material is null)::text, '0'
  union all select 'neto mal calculado = 0',
    (select count(*) from models where round(neto, 4) <> round(precio_rebaja * (1 - margen), 4))::text, '0'
  union all select 'rebaja > precio = 0',
    (select count(*) from models where precio_rebaja > precio)::text, '0'
)
select
  case when got = want then 'PASS' else 'FAIL' end as status,
  prueba, want, got
from checks
order by (got = want), prueba;
