-- Forum Sport · dynamic pricing dataset
-- Source: dataset/Dataset_FS_pricing_dinámico.xlsx (tab "bbdd")
--
-- Grain of the source sheet is one row per SKU, with the 25 model-level
-- attributes repeated across every size of a model. That repetition was
-- verified to be perfectly consistent (no model-level column varies within a
-- Modelo), so the sheet splits losslessly into models (1,483) + skus (24,109).

create table if not exists brands (
  code text primary key,                -- "Marca (código)", e.g. ADIDAS  (28 rows)
  name text not null                    -- "Descmarca",      e.g. adidas
);

comment on table brands is 'Marcas. Mapeo 1:1 entre código y nombre comercial.';

create table if not exists models (
  -- Identity -----------------------------------------------------------
  modelo           bigint primary key,  -- "Modelo": código interno = producto + color
  brand_code       text     not null references brands(code),
  nombre_modelo    text     not null,   -- "Nombremodelo"
  color            text,                -- "Color": 12 códigos; en blanco -> NULL
  ref_color_prov   integer,             -- "Ref Color Prov": 846 modelos sin dato
  ref_prov         text     not null,   -- "Ref Prov (MODELO)"
  gr               text     not null,   -- "Gr": familia; muchos-a-uno sobre tipo_producto
  temporada        text     not null check (temporada in ('AN', 'OI', 'PV')),
  ano_temporada    smallint not null,   -- 9998 = centinela "sin año" (2 modelos)
  tipo_producto    text     not null,

  -- Gestión ------------------------------------------------------------
  exclusivo_online boolean  not null,   -- "Exclusivoonline": '' / 'ExclusivoOnline'
  outlet           boolean  not null,   -- "Outlet": NO / SI
  cat_extendido    boolean  not null,   -- "Cat.extendido": 0 / 1
  custom_label     text,                -- "Customlabel": 0-4, A, B, D, J, K; '' -> NULL
  abcd_tienda      text check (abcd_tienda  in ('AA', 'A', 'B', 'C', 'D')),
  abcd_digital     text check (abcd_digital in ('AA', 'A', 'B', 'C', 'D')),

  -- Precio -------------------------------------------------------------
  precio           numeric(10, 2) not null check (precio > 0),  -- "Precio2"  (PVP)
  precio_rebaja    numeric(10, 2) not null,                     -- "Rebaja2"
  margen           numeric(4, 3)  not null check (margen in (0.15, 0.2, 0.3, 0.4)),
  nivel_margen     text not null check (nivel_margen in ('muy bajo', 'bajo', 'medio', 'alto')),

  -- Stock --------------------------------------------------------------
  cobertura_stock  integer,             -- NULL = 'SIN DATOS COBERTURA' (249 modelos)
  nivel_stock      text not null
    check (nivel_stock in ('muy bajo', 'bajo', 'medio', 'alto', 'muy alto')),
  online           boolean not null,

  constraint rebaja_lte_precio check (precio_rebaja <= precio),

  -- Derivados ----------------------------------------------------------
  -- Reproduce "NETO SINTÉTICO*" del origen: verificado exacto en las 24.109 filas.
  neto numeric generated always as (precio_rebaja * (1 - margen)) stored,

  descuento_pct numeric generated always as (
    round((precio - precio_rebaja) / precio * 100, 2)
  ) stored,

  en_rebaja boolean generated always as (precio_rebaja < precio) stored,

  -- Patrón de URL documentado en la pestaña "campos" del origen.
  url text generated always as (
    'https://www.forumsport.com/es-es/-' || modelo::text || '-p'
  ) stored,

  -- Orden natural de los niveles, para que el frontend ordene sin mapas locales.
  nivel_margen_orden smallint generated always as (
    (case nivel_margen when 'muy bajo' then 1 when 'bajo' then 2
                       when 'medio'    then 3 when 'alto' then 4 end)::smallint
  ) stored,

  nivel_stock_orden smallint generated always as (
    (case nivel_stock when 'muy bajo' then 1 when 'bajo'     then 2
                      when 'medio'    then 3 when 'alto'     then 4
                      when 'muy alto' then 5 end)::smallint
  ) stored
);

comment on table  models                is 'Modelo = producto + color. Unidad de gestión interna.';
comment on column models.ano_temporada  is '9998 es un centinela de "sin año", no un año real.';
comment on column models.cobertura_stock is 'NULL representa "SIN DATOS COBERTURA" en el origen.';
comment on column models.neto           is 'Derivado: precio_rebaja * (1 - margen).';

create table if not exists skus (
  material bigint primary key,          -- "Material (sku)"
  modelo   bigint not null references models(modelo) on delete cascade,
  talla    numeric(4, 1) not null,      -- "Talla": escala del proveedor (admite .5)
  talla_es smallint      not null,      -- "TALLA ES": equivalente español
  ean      bigint        not null unique
);

comment on table skus is 'Cada modelo tiene varias tallas; cada talla es un material (SKU).';

-- Índices para los filtros y agregaciones de la landing ------------------
create index if not exists idx_models_brand         on models (brand_code);
create index if not exists idx_models_tipo          on models (tipo_producto);
create index if not exists idx_models_nivel_margen  on models (nivel_margen_orden);
create index if not exists idx_models_nivel_stock   on models (nivel_stock_orden);
create index if not exists idx_models_temporada     on models (temporada, ano_temporada);
create index if not exists idx_models_outlet        on models (outlet) where outlet;
create index if not exists idx_models_en_rebaja     on models (en_rebaja) where en_rebaja;
create index if not exists idx_models_precio        on models (precio);
create index if not exists idx_models_descuento     on models (descuento_pct desc);

create index if not exists idx_skus_modelo          on skus (modelo);
create index if not exists idx_skus_talla_es        on skus (talla_es);
