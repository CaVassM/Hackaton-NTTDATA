"""Extraccion guiada por el RAG: la verificacion determinista manda sobre el LLM."""
from modules.compliance import EstadoPropuesta
from modules.compliance.extraction.citation_check import cita_literal, numero_en_cita
from modules.compliance.tests.conftest import (
    NORMA_2660,
    NORMA_SINT,
    make_facade,
    oracion_con,
    responder_correcto,
)


def test_citation_check_basico():
    texto = "La comunicación debe ser\nrealizada  en un plazo que no exceda las veinticuatro horas (24) desde la calificación."
    assert cita_literal("La comunicación debe ser realizada en un plazo", texto)  # normaliza espacios
    assert not cita_literal("La comunicación debe hacerse en un plazo breve", texto)
    assert not cita_literal("debe ser", texto)  # demasiado corta para probar algo
    assert numero_en_cita(24, "las veinticuatro horas (24)") and numero_en_cita(10, "diez años")
    assert not numero_en_cita(15, "las veinticuatro horas (24)")


def test_extraccion_correcta_crea_propuestas_con_version_y_categoria(rag, tmp_path):
    f, llm = make_facade(rag, tmp_path, responder_correcto)
    s = f.extract_obligations(["BAN-004"])
    assert s.propuestas_nuevas >= 1 and s.descartadas == 0
    (ros,) = [o for o in f.proposals()["obligaciones"] if o.plazo_valor == 24]
    assert (ros.categoria, ros.norma_codigo, ros.articulo_numero) == ("BAN-004", NORMA_2660, "58")
    assert ros.plazo_unidad == "horas" and ros.revision.estado == EstadoPropuesta.PROPUESTA
    assert rag.get_version(ros.version_id).articulo_numero == "58"


def test_cita_inexistente_se_descarta(rag, tmp_path):
    def inventa(prompt, schema):
        return {"impone_obligacion": True, "obligaciones": [dict(
            sujeto="la empresa", accion_requerida="reportar", plazo_valor=None,
            cita_textual="La empresa debe reportar toda operación sospechosa en un plazo de tres días hábiles.")]}

    f, _ = make_facade(rag, tmp_path, inventa)
    s = f.extract_obligations(["BAN-004"])
    assert s.propuestas_nuevas == 0 and s.descartadas == s.articulos
    assert f.proposals()["obligaciones"] == []


def test_plazo_que_no_aparece_en_la_cita_se_descarta(rag, tmp_path):
    def plazo_inventado(prompt, schema):
        c = oracion_con(prompt, r"veinticuatro horas \(24\)")
        if not c:
            return {"impone_obligacion": False, "obligaciones": []}
        return {"impone_obligacion": True, "obligaciones": [dict(
            sujeto="la empresa", accion_requerida="comunicar el ROS", plazo_valor=48, plazo_unidad="horas",
            cita_textual=c)]}

    f, _ = make_facade(rag, tmp_path, plazo_inventado)
    s = f.extract_obligations(["BAN-004"])
    assert s.descartadas == 1 and s.propuestas_nuevas == 0


def test_cache_reanudable_no_vuelve_a_llamar_al_llm(rag, tmp_path):
    f, llm = make_facade(rag, tmp_path, responder_correcto)
    s1 = f.extract_obligations(["BAN-004"])
    llamadas = llm.calls
    s2 = f.extract_obligations(["BAN-004"])
    assert llm.calls == llamadas and s2.desde_cache == s1.articulos
    assert s2.propuestas_nuevas == 0 and s2.duplicadas == s1.propuestas_nuevas


def test_json_invalido_reintenta_y_no_aprueba(rag, tmp_path):
    def roto(prompt, schema):
        return {"impone_obligacion": "quizas", "obligaciones": "?"}

    f, llm = make_facade(rag, tmp_path, roto)
    s = f.extract_obligations(["BAN-004"])
    assert s.errores == s.articulos and llm.calls == 2 * s.articulos and s.propuestas_nuevas == 0


def test_infracciones_montos_fuera_de_la_cita_se_anulan_y_cita_falsa_se_descarta(rag, tmp_path):
    def montos_inventados(prompt, schema):
        r = responder_correcto(prompt, schema)
        for i in r["infracciones"]:
            i["multa_max_uit"] = 999.0  # no esta en la cita
        if r["infracciones"]:
            r["infracciones"].append(dict(descripcion="falsa", cita_textual="Infracción inventada por el modelo sin sustento."))
        return r

    f, _ = make_facade(rag, tmp_path, montos_inventados)
    s = f.extract_infractions(["BAN-004"])
    infs = f.proposals()["infracciones"]
    assert infs and all(i.multa_max_uit is None for i in infs)
    assert s.descartadas >= 1 and all(i.norma_codigo == NORMA_SINT for i in infs)
    assert f.proposals()["enlaces"]  # enlace categoria->infraccion como propuesta


def test_infracciones_reales_2755_no_trae_el_anexo_sintetico(rag, tmp_path):
    f, _ = make_facade(rag, tmp_path, responder_correcto, norma_inf="Resolución SBS N° 2755-2018")
    f.extract_infractions(["BAN-004"])
    assert all(i.norma_codigo != NORMA_SINT for i in f.proposals()["infracciones"])
