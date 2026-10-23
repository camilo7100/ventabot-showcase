# Reglas de negocio — supuestos marcados [POR DEFINIR]

Todo lo de este documento vive en **`config/reglas.yaml`**. Son **datos, no
código**: cambiarlos no requiere tocar Python ni volver a desplegar.

Los **33 valores marcados `[POR DEFINIR]`** son suposiciones mías, tomadas para
que el sistema funcione hoy. Abajo explico qué elegí y por qué, para que puedas
ajustar con criterio en vez de adivinar.

Para ver qué sigue pendiente en cualquier momento:

```bash
python -c "from pathlib import Path; from app.infra.reglas import marcadores_por_definir; \
[print(f'{l:3}  {t}') for l, t in marcadores_por_definir(Path('config/reglas.yaml'))]"
```

---

## Las 6 decisiones que más te conviene revisar primero

| # | Regla | Mi supuesto | Por qué | Impacto si me equivoqué |
|---|---|---|---|---|
| 1 | `anticipo_pct_default` | **50%** | Estándar en fabricación a pedido: cubre materiales y filtra clientes no serios | Alto — es tu flujo de caja |
| 2 | `permitir_transferencia_para_anticipo` | **false** | El fraude con comprobantes falsos de Nequi está industrializado en Colombia y ataca justo aquí. Con anticipo por link, el estafador no puede hacerte producir | Alto — es tu principal defensa |
| 3 | `iva_pct` / `responsable_de_iva` | **19% / sí** | Régimen general. Si eres no responsable de IVA, pon `0.00` y `false` | Alto — cotizas mal el 19% |
| 4 | `cantidad_maxima_automatica` | **20** | Por encima de eso probablemente hay descuento por volumen que el bot no sabe dar | Medio — pierdes o regalas margen |
| 5 | `descuento_maximo_automatico_pct` | **0.0** | En v1 el bot **no negocia**. Todo descuento pasa por un humano | Medio — conservador a propósito |
| 6 | `envio_gratis_desde_cop` | **400.000** | Umbral típico para subir el ticket promedio | Medio — afecta margen |

---

## Todas las reglas, por sección

### `negocio`
| Regla | Supuesto | Nota |
|---|---|---|
| `nombre`, `nit`, `ciudad_origen` | placeholders | Necesarios para facturación DIAN (Fase 6) |
| `whatsapp_display_name` | `"Mi Negocio"` | ⚠️ Debe coincidir **exactamente** con tu sitio web y **solo se cambia cada 30 días**. Piénsalo antes de registrarlo en Meta |

### `horario`
| Regla | Supuesto | Nota |
|---|---|---|
| `dias_habiles` | lun–sáb | El bot responde 24/7 igual (es automático); esto rige el *handoff* humano y las fechas prometidas |
| `hora_inicio` / `hora_fin` | 08:00–18:00 | Fuera de horario, el escalado a humano se encola en vez de notificar |
| `sabado_hora_fin` | 13:00 | |

### `impuestos`
| Regla | Supuesto | Nota |
|---|---|---|
| `iva_pct` | 0.19 | |
| `responsable_de_iva` | true | **Confírmalo con tu contador.** Si no eres responsable, todo el cálculo cambia |
| `incluir_iva_en_precio_mostrado` | true | El cliente ve el precio final. Es lo normal en venta al consumidor |

### `pagos`
| Regla | Supuesto | Nota |
|---|---|---|
| `anticipo_pct_default` | 0.50 | Se puede sobrescribir por producto en `data/catalogo.csv` |
| `redondeo_anticipo_cop` | 1000 | Para que el cliente vea $109.000 y no $108.650 |
| `vigencia_link_horas` | 72 | Coincide con la ventana gratis de Click-to-WhatsApp |
| `vigencia_cotizacion_horas` | 48 | Después se re-cotiza (protege de cambios de costo) |
| `recordatorio_anticipo_horas` | [24, 72] | Dos toques y ya. Más se siente acoso |
| `recordatorio_saldo_horas` | [24, 48, 96] | Aquí sí insistes: el producto ya está fabricado |
| `cancelar_por_falta_de_anticipo_horas` | 168 (7 días) | Libera capacidad de producción |
| `metodos_habilitados` | tarjeta, PSE, Nequi | Los tres que cubren la mayor parte del mercado colombiano |
| `permitir_transferencia_para_anticipo` | **false** | Ver decisión #2 arriba |
| `permitir_transferencia_para_saldo` | true | Menor riesgo: ya hay dinero tuyo y compromiso del cliente |
| `umbral_verificacion_manual_cop` | 300.000 | Por encima, nadie despacha sin ver el abono en el extracto |
| `no_despachar_contra_comprobante_dias` | vie, sáb, dom | El fraude se concentra cuando la verificación bancaria es más lenta |
| `usar_monto_con_digitos_unicos` | true | $150.000 → $150.037. Hace determinística la conciliación manual |

### `envios`
| Regla | Supuesto | Nota |
|---|---|---|
| `costo_default_cop` | 15.000 | Se usa solo si la ciudad no está en `data/fletes.csv` |
| `envio_gratis_desde_cop` | 400.000 | `0` = nunca hay envío gratis |
| `transportadora_default` | Interrapidísimo | Cambia por la que uses |

La tabla real de fletes está en **`data/fletes.csv`**: 29 ciudades con costo y
días de transporte, organizadas en zonas LOCAL / PRINCIPAL / INTERMEDIA /
ESPECIAL. Búsqueda insensible a tildes y mayúsculas ("medellin" = "Medellín").

### `produccion`
| Regla | Supuesto | Nota |
|---|---|---|
| `dias_produccion_default` | 7 | Solo si el producto no lo especifica |
| `dias_transporte_default` | 3 | |
| `colchon_dias` | 2 | Se suma a la fecha que le prometes al cliente. **Prometer de menos y cumplir vale más que prometer rápido e incumplir** |
| `capacidad_pedidos_simultaneos` | 20 | `0` = sin límite. Al llegar al tope, el bot avisa fechas más largas |

### `conversacion`
| Regla | Supuesto | Nota |
|---|---|---|
| `fallos_nlu_antes_de_handoff` | 2 | Dos fallos y pasa a un humano. Nunca un tercer intento |
| `duracion_handoff_horas` | 4 | Mientras tanto el bot **se calla** |
| `max_productos_por_mensaje` | 10 | Límite duro de WhatsApp: una lista interactiva admite 10 filas |
| `timeout_conversacion_horas` | 24 | Cierra la conversación, **no** el pedido |
| `cantidad_maxima_automatica` | 20 | |
| `descuento_maximo_automatico_pct` | 0.0 | |

### `datos_personales`
| Regla | Supuesto | Nota |
|---|---|---|
| `version_politica` | `v1-2026-08` | Se guarda en el cliente qué versión aceptó |
| `url_politica` | placeholder | Necesitas publicarla antes de operar |
| `pedir_consentimiento_en_primer_contacto` | true | Ley 1581 de 2012 |
| `retencion_chats_meses` | 24 | Los logs de chat **son datos personales** |
| `retencion_comprobantes_meses` | 60 | 5 años, criterio contable |

> No es asesoría legal. Valida las reglas fiscales con tu contador y las de
> habeas data con un abogado antes de operar.

---

## Catálogo semilla (`data/catalogo.csv`)

15 productos inventados de un negocio de **personalización y fabricación a
pedido** (textil, merchandising, letreros), porque encaja con tu modelo de
anticipo-para-fabricar. Reemplázalos por los tuyos: es un CSV, se edita en
Excel.

| Columna | Para qué |
|---|---|
| `sku` | Identificador único. El validador de Pydantic rechaza SKUs que no existan aquí — así el LLM no puede inventar productos |
| `precio_cop` | **Entero en pesos.** Nunca decimales para dinero |
| `dias_produccion` | Se usa para prometer la fecha de entrega |
| `anticipo_pct` | Sobrescribe el default por producto (los letreros piden 60%) |
| `cantidad_minima` | Pedido mínimo. **Aún no se aplica en código** — Fase 2 |
| `activo` | `FALSE` lo saca del catálogo sin borrar el histórico |
