# transcripcion Specification

## Purpose

Convertir el audio de cada nota de voz del operador en texto, en la PC de planta, sin enlace y dentro del presupuesto
de CPU, con la calidad que necesita el parte: números, nombres de equipos y unidades bien transcritos.

## Requirements

### Requirement: La transcripción es local y en CPU

El sistema SHALL transcribir con faster-whisper `small` int8 en español, en CPU, con 2 hilos
(`STT_MODELO=whisper:small`, `STT_HILOS`). El modelo SHALL estar dentro de la imagen del sistema: SHALL NOT
descargarse en runtime.

**Razón:** medido sobre las 102 notas del banco de voces de la planta con su ruido, en 2 CPU
(`evaluacion/stt/`): Whisper small int8 da 1,2 % de error por palabra, 97 % de notas con todos los números bien y
p95 de 6,3 s. Parakeet TDT 0.6B es más rápido pero cambia de idioma a mitad de nota y junta diferenciales ("uno dos"
→ 12): 54 % de notas con los números bien. Whisper large-v3-turbo pasa los 20 s por nota. La red de planta no tiene
internet y el corrector borra los volúmenes entre escenarios, por eso el modelo va en la imagen.

#### Scenario: Arranque sin internet
- **WHEN** el sistema arranca en la red de planta, sin salida a internet y con los volúmenes recién creados
- **THEN** el transcriptor queda listo con el modelo de la imagen

#### Scenario: Calidad y latencia
- **WHEN** se corre `evaluacion/stt/` sobre el banco de voces con ruido de planta, en 2 CPU
- **THEN** al menos el 95 % de las notas tiene todos los números bien
- **AND** el p95 de la latencia por nota es menor a 10 s

### Requirement: El prompt da el vocabulario de la planta

La transcripción SHALL usar un prompt inicial con los nombres de los equipos y una frase de dictado típica ("La dos
está en mil seiscientos psi de descarga. El filtro B me dio uno ocho de diferencial.") y SHALL NOT condicionar cada
segmento al texto anterior.

**Razón:** con el prompt de la planta el error por palabra bajó de 6,5 % a 1,2 %.

#### Scenario: Nombres de equipos
- **WHEN** el operador dice "el filtro B me dio uno ocho de diferencial"
- **THEN** la transcripción conserva "filtro B" y los números hablados para que la extracción los convierta

### Requirement: El audio se baja de la planta y se normaliza

El sistema SHALL bajar el audio de `PLANTA_URL` + `audio_url` de la nota y SHALL aceptar WAV PCM de 16 bits, mono o
estéreo, a cualquier frecuencia, llevándolo a mono float32 a 16 kHz. Un WAV con otra profundidad MUST fallar con un
error claro. Una nota sin `audio_url` SHALL tratarse como texto vacío.

#### Scenario: WAV estéreo a 44,1 kHz
- **WHEN** llega un WAV PCM 16 bits estéreo a 44,1 kHz
- **THEN** se transcribe un audio mono a 16 kHz de la misma duración

### Requirement: Una transcripción por vez

El sistema SHALL transcribir de a una nota por vez; las demás esperan su turno. Cada transcripción SHALL quedar
registrada como paso de la nota con el modelo, la duración y los segundos de audio.

**Razón:** la CPU de planta se comparte con el LLM, la base y las tools; dos transcripciones en paralelo demoran a
las dos, y la nota insegura tiene 30 s para la alerta.

#### Scenario: Dos notas juntas
- **WHEN** llegan dos notas en el mismo segundo
- **THEN** se transcribe una y la otra espera
- **AND** las dos quedan registradas en la tabla `pasos` con su duración
