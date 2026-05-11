import UploadBox from "../components/UploadBox";

export default function Home() {

  return (

    <main className="min-h-screen bg-blue-50 flex flex-col items-center justify-center p-10">

      <h1 className="text-5xl font-bold text-blue-900 mb-3">
        AutoPivot Agent
      </h1>

      <p className="text-blue-700 mb-10">
        AI Vehicle Privacy Tool
      </p>

      <UploadBox />

    </main>

  );
}
