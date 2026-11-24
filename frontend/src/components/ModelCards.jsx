import AnnNotice from "./AnnNotice.jsx";
import CompareCard from "./CompareCard.jsx";
import TrainCard from "./TrainCard.jsx";

// The cards under the two panels: the Train card only for the linear model (the ANN is fixed, so a short notice
// says so instead), and the Compare card for both. Nothing about training is shown until the model is known.
export default function ModelCards({ model, onTrained }) {
  return (
    <>
      {model?.trainable && <TrainCard onTrained={onTrained} />}
      {model && !model.trainable && <AnnNotice model={model} />}
      <CompareCard />
    </>
  );
}
