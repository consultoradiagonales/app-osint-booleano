# Perfil OSINT político · Saladillo, Provincia y Nación

Fecha de corte: 2026-08-16. Alcance: fuentes abiertas, sin acceso autenticado ni extracción de datos personales.

## Integración operativa

El perfil se ejecuta contra el catálogo de **253 URL públicas** de `config/AGENCIA_DE_NOTICIAS.md`: registros oficiales, boletines, organismos nacionales y provinciales, municipios de la 7ª sección, medios nacionales, medios políticos y medios regionales. Ese catálogo es la fuente única de URL de la agencia; el motor excluye redes sociales, buscadores, herramientas y dominios no editoriales.

Consulta de producción:

```text
((Grupo Saladillo) OR (Grupo Provincia) OR (Grupo Nación))
AND (política OR gobierno OR legislatura OR concejo OR elecciones OR candidato OR intendente OR gobernador OR diputado OR senado OR presupuesto OR IOMA)
```

Cada grupo contiene los nombres, siglas y variantes ortográficas del pedido editorial. Se usa `OR` entre territorios para captar una noticia relevante en cualquiera de ellos; exigir los tres con `AND` descartaría casi todas las notas reales. El requisito político queda separado y obligatorio.

El monitor guardado `politica` usa este perfil de lunes a viernes a las 09:00, 15:00 y 20:00. Los fines de semana quedan excluidos hasta que el cliente los active.

## Resultado de la prueba OSINT

La consulta literal original, con los tres grupos unidos mediante `AND`, produjo 0 coincidencias verificables: una sola nota rara vez menciona simultáneamente Saladillo, Provincia y Nación. El perfil de producción corrige esa condición sin ampliar el universo a deportes, clima, espectáculos o temas ajenos: exige al menos un actor pedido y un contexto político/legislativo/económico público.

Hallazgos y enlaces se conservan en cada corrida con URL, fecha, fuente y evidencia. El sistema no atribuye hechos no corroborados ni convierte ausencia de resultados en una conclusión.

## Modelo comercial para Consultora Diagonales

La unidad vendible no es “muchas URLs”; es una **alerta política priorizada, segmentada y trazable**. La oferta inicial debe tener tres capas:

1. **Monitor territorial**: una consulta guardada, hasta tres horarios, días elegidos, cable HTML y archivo de enlaces.
2. **Radar de actores**: varias consultas/territorios, ranking por relevancia y menciones, histórico y RSS privado.
3. **Brief estratégico**: radar más síntesis editorial y radiografía periódica; requiere una fuente de IA operativa o trabajo editorial contratado.

Precio sugerido: abono mensual por perfil activo y número de destinatarios; alta inicial para diseño de la consulta; adicional por cobertura urgente, archivo histórico o informe estratégico. No vender “IA infalible”: vender trazabilidad, fuentes múltiples, reglas explícitas y velocidad.

## Referencias de modelos comparables

- [Reuters Connect](https://reutersagency.com/content-delivery-platforms/reuters-connect/) combina suscripción flexible, búsqueda, alertas, agenda editorial, API y múltiples proveedores de contenido.
- [Associated Press Solutions](https://www.ap.org/solutions/) comercializa plataforma de entrega, resultados electorales, producción y servicios de contenido.
- [EFE para empresas](https://efe.com/para-empresas/) segmenta por importancia, temática y territorio, y adapta la selección a empresa, competidor, tema o persona.
- [EFE Servicios](https://efe.com/efe-servicios/) combina plataforma para suscriptores, archivo y compra puntual de contenidos.
- [EFE Comunica](https://efecomunica.efe.com/) agrega consultoría, contenidos, difusión y eventos a la capa informativa.

La versión viable con presupuesto inicial cero replica sólo la estructura: catálogo público + perfiles guardados + RSS/HTML + evidencia. Licenciar o redistribuir textos/fotos íntegros de agencias o medios requiere derechos comerciales; Diagonales debe enviar enlaces, metadatos y redacción propia breve hasta contar con licencias.
