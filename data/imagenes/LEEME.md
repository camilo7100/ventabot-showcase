# Las imágenes del bot

Aquí está **solo lo que se le manda a la clienta** (y lo que sirve `/media/<nombre>`). El
código las pide por su nombre sin extensión (`muestrario_circones`), así que cambiar una
foto es reemplazar el archivo con el **mismo nombre**: no se toca código.

| Archivo | Cuándo se manda |
|---|---|
| `presentacion_video_1.mp4`, `presentacion_video_2.mp4` | Al presentar el anillo (catálogo) |
| `presentacion_anillo.jpg` | Al presentar el anillo, con «¿sabes tu talla?» |
| `medir_talla_guia.jpg` | Cuando se pide la guía de la talla |
| `medir_talla_ejemplo_2.jpg` | Con la guía de la talla (camino viejo, sin asesora) |
| `muestrario_circones.jpg` | **Al preguntar los colores**: los circones con el nombre de cada color (la de Camilo, 30/09; reemplazada el 02/10 desde «Nueva imagen a mandar.PNG», 1600×2000) |
| `anillos_inspirado_en_tu_mascota.jpg`, `anillo_ejemplo_1.jpg`, `muestrario_circones.jpg` | Cuando pide ver anillos hechos (ejemplos). 13/10: salió `anillo_ejemplo_3` (un anillo DORADO sobre una regla, no es nuestro) |
| `anillos_inspirado_en_tu_mascota.jpg` | El collage «Inspirado en tu mascota · Plata Ley 925» (seis anillos reales con nombres; de `IMG_7525.PNG` de Camilo, 15/10, solo reducida a 1355×1600). Va en **todos** los sitios donde iba la del anillo rojo «Bjorn ♡» (que a Camilo no le gustó): la apertura del peludito, los ejemplos, los recordatorios (y su cabecera de plantilla) y la foto del «Anillo huellita x1» en el catálogo de WhatsApp |
| `anillo_video_1.mp4`, `anillo_video_2.mp4` | Videos del anillo (camino viejo, sin asesora) |
| `cadena_1.jpg`, `cadena_2.jpg`, `cadena_3.jpg` | Con el mensaje de la cadena, **solo si ella pregunta** por cadenas o por más productos (03/10, fotos de Camilo: Mía con las anotaciones, Pepi, Lupe con el reverso) |
| `anillo_corazon_1.jpg` | Con la presentación del **anillo de corazón** (17/10; SÍ se ofrece, desde el primer mensaje): el corazón fucsia con dos circones a los lados, en su estuche rosado. De `IMG_7534.PNG` de Camilo, solo pasada a JPG (1024×1535). Es también su `imagen_url` en `data/catalogo.csv` |
| `anillo_corazon_2.jpg` | La otra toma del mismo anillo (`IMG_7535.JPEG`, sin tocar): de repuesto, el bot no la manda |
| `catalogo_anillo_2.jpg`, `catalogo_anillo_3.jpg` | Son las fotos del catálogo del perfil de WhatsApp (Meta las baja de `/media`; la cadena usa `cadena_2`). Recortes sin retoque de la foto del anillo rojo de 1 huellita y de `presentacion_anillo` (03/10). Cuál va con cada producto lo dice `imagen_url` de `data/catalogo.csv` |

`fuentes/` tiene lo que el bot **usa pero no manda**:

| Archivo | Para qué |
|---|---|
| `huellita_base.jpg`, `huellita_mascaras.png` | Dibujar «así se te vería» con los colores elegidos |
| `muestrario_circones_original.jpg` | La foto sin letras que mide `vb muestrario` para sacar el color de cada circón |

Ordenado el 02/10/2026: se borraron dos copias exactas (`medir_talla_ejemplo_1` era la
misma foto que `anillo_ejemplo_3`; `anillo_ejemplo_2` y `muestrario_circones_2` eran la foto
vieja de los circones sin nombres, que ahora es la del muestrario con nombres).
