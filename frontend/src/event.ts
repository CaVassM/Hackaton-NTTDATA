/* Datos del evento que se muestran en la interfaz. Editar solo aquí. */
export const EVENTO = {
  hackaton: "Hackatón NTT DATA",
  grupoNumero: 10,
  // Nombre del grupo: completar aquí si el equipo tiene uno (se muestra solo si no está vacío).
  grupoNombre: "",
  integrantes: ["Carlos Vasquez", "Kennedy de la Torre"],
};

export const grupoEtiqueta = () =>
  `Grupo N.° ${EVENTO.grupoNumero}${EVENTO.grupoNombre ? ` · ${EVENTO.grupoNombre}` : ""}`;
