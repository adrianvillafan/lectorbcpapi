from flask import Flask, request, jsonify
import easyocr
import re
from datetime import datetime
import locale
import cv2

locale.setlocale(locale.LC_ALL, "es_ES.UTF-8")

reader = easyocr.Reader(['es'])

app = Flask(__name__)

@app.route('/procesar_boucher', methods=['POST'])
def procesar_boucher():
    try:
        imagen = request.files['imagen']
        
        imagen_path = 'temp_image.jpg'
        imagen.save(imagen_path)

        result = reader.readtext(cv2.imread(imagen_path))

        filas = agrupar_en_filas(ordenar_por_altura(result))
        monto, fecha, numero_operacion, destino = bcp(filas)

        response = {
            "monto": monto,
            "fecha": fecha,
            "numero_operacion": numero_operacion,
            "destino": destino
        }

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)})

###########- ORDEN DE DATOS LEIDOS -###########

def ordenar_por_altura(resultados):
    # Ordenar los resultados por la coordenada y del primer punto de cada elemento
    resultados_ordenados = sorted(resultados, key=lambda x: x[0][0][1])
    return resultados_ordenados

def agregar_obs_si_necesario(valor_confianza):
    try:
        valor, confianza = valor_confianza
    except (TypeError, ValueError):
        return [None,None,"Obs"]

    if confianza is None or confianza < 0.6:
        return valor_confianza + ["Obs"]
    else:
        return valor_confianza + [""]


def agrupar_en_filas(resultados_ordenados, umbral_distancia=30):
    filas = []
    fila_actual = []
    for i, (coordenadas, texto, probabilidad) in enumerate(resultados_ordenados):
        if i == 0:
            fila_actual.append((coordenadas, texto, probabilidad))
            continue
        y_min_fila_actual = min(coordenada[1] for coordenada in fila_actual[-1][0])
        y_max_fila_actual = max(coordenada[1] for coordenada in fila_actual[-1][0])
        y_min_actual = min(coordenada[1] for coordenada in coordenadas)
        y_max_actual = max(coordenada[1] for coordenada in coordenadas)
        y_promedio_actual = (y_min_actual + y_max_actual) / 2
        y_promedio_fila_actual = (y_min_fila_actual + y_max_fila_actual) / 2
        distancia_vertical = abs(y_promedio_fila_actual - y_promedio_actual)
        altura_fila = y_max_fila_actual - y_min_fila_actual
        porcentaje_distancia = (distancia_vertical / altura_fila) * 100
        if porcentaje_distancia <= umbral_distancia:
            fila_actual.append((coordenadas, texto, probabilidad))
        else:
            filas.append(fila_actual)
            fila_actual = [(coordenadas, texto, probabilidad)]
    if fila_actual:
        filas.append(fila_actual)
    for fila in filas:
        fila.sort(key=lambda x: x[0][0][0])
    filas_amigables = []
    for fila_ocr in filas:
        fila_amigable = [fila_ocr[0][1:]]
        for coordenada, texto, probabilidad in fila_ocr[1:]:
            fila_amigable.append((texto,probabilidad))
        filas_amigables.append(fila_amigable)
    return filas_amigables

###########- NORMALIZACION Y FILTRADO DE DATOS (BCP) -###########

def bcp(filas):
    monto, filas_restantes = buscar_monto(filas)
    fecha, filas_restantes = buscar_fecha(filas_restantes)
    destino, filas_restantes = buscar_destino(filas_restantes)
    numero_operacion = buscar_numero_operacion(filas_restantes)
    return agregar_obs_si_necesario(monto), agregar_obs_si_necesario(fecha), agregar_obs_si_necesario(numero_operacion), agregar_obs_si_necesario(destino)

def buscar_monto(filas):
    for i, fila in enumerate(filas):
        for texto in fila:
            prob = texto[1]
            texto = texto[0]
            if re.search(r'\d{3}\.00', texto):
                monto = re.search(r'\d{3}\.00', texto).group()
                monto = monto.replace('.00', '')
                monto = re.sub(r'\D', '', monto)
                return [monto,prob], filas[i+1:]
            elif any(numero in texto for numero in ['350', '400', '450', '500']):
                monto = re.search(r'\d+', texto).group()
                return [monto,prob], filas[i+1:]
    return "No se encontró monto", filas

def buscar_fecha(filas):
    dias_semana = ['lunes', 'martes', 'miércoles','miercoles', 'jueves', 'viernes', 'sábado', 'sabado', 'domingo']
    for fila in filas:
        fil = fila
        filar =[]
        prob = []
        for i in range(len(fila)):
            filar.append(fila[i][0])
            prob.append(fila[i][1])
        fila = filar
        for dia in dias_semana:
            if any(dia in elemento.lower() for elemento in fila):
                palabras = ' '.join(fila).split()  # Unimos la fila y la dividimos en palabras
                for i, palabra in enumerate(palabras):
                    for clave, valor in {'iercoles': 'iércoles', 'abado': 'ábado'}.items():
                        if clave in palabra:
                            palabras[i] = palabra.replace(clave, valor)
                fecha_texto = ' '.join(palabras)  # Reunimos las palabras corregidas nuevamente
                # Buscar el año dentro de la cadena
                palabras = fecha_texto.split()
                for i, palabra in enumerate(palabras):
                    if len(palabra) == 4 and palabra.isdigit():
                        # Encontramos el año, cortamos la cadena hasta este punto
                        fecha_texto = ' '.join(palabras[:i+1])
                        break
                for formato in [r"%A, %d %B %Y", r"%A; %d %B %Y", r"%A %d %B %Y"]:
                    try:
                        fecha = datetime.strptime(fecha_texto, formato)
                        return [fecha.strftime(r"%d/%m/%Y"),prob[0]], filas[filas.index(fil) + 1:]
                    except ValueError:
                        continue
    return None, filas

def buscar_destino(filas):
    for fila in filas:
        for elemento in fila:
            prob = elemento[1]
            elemento = elemento[0]
            if 'Pagos Varios' in elemento or "Varios" in elemento:
                return ["Servicio",prob], filas[filas.index(fila) + 1:]
            elif 'Moneda' in elemento or "Moneda Soles" in elemento:
                return ["Cuenta Corriente",prob], filas[filas.index(fila) + 1:]
    return None, filas

def buscar_numero_operacion(filas):
    #print(filas)
    operacion = None
    for fila in filas:
        fil = fila
        filar =[]
        prob = []
        #print("Fila 1 :" ,fila)
        for i in range(len(fila)):
            filar.append(fila[i][0])
            prob.append(fila[i][1])
        fila = filar
        #print("Fila final :" ,fila)
        texto = ' '.join(fila)
        if any(keyword in texto.lower() for keyword in ['número de operación', 'numero de operacion', 'operación', 'operacion']):
            matches = re.findall(r'\d{8}', texto)
            if matches:
                for match in matches:
                    if match.isnumeric() and len(match) == 8:
                        return  [match,prob[0]]
            else:
                numero = ''.join(re.findall(r'\d+', texto))
                if len(numero) >= 8:
                    return [numero[:8],prob[0]]
                else:
                    for i, fila_siguiente in enumerate(filas[filas.index(fil) + 1:]):
                        texto_siguiente = ' '.join(fila_siguiente[0][0])
                        numero += ''.join(re.findall(r'\d+', texto_siguiente))
                        if not numero.isdigit():
                            break
                        if len(numero) >= 8:
                            return [numero[:8],prob[0]]
    return operacion

if __name__ == '__main__':
    app.run(debug=True)

